import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

# Single, module-level S3 client
s3_client = boto3.client("s3")

# Force-download file extensions
_FORCE_DOWNLOAD_EXTENSIONS = (
    ".mp4",
    ".mov",
    ".avi",
    ".wmv",
    ".flv",
    ".mp3",
    ".mkv",
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".jpeg",
    ".jpg",
    ".png",
    ".odt",
    ".gif",
)

DEFAULT_PRESIGNED_URL_TTL = getattr(settings, "PRESIGNED_URL_TTL", 60*60)

def _parse_s3_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path.lstrip("/")
    bucket_name = None
    object_key = None

    # virtual hosted
    if host.endswith(".amazonaws.com") and ("s3." in host or "s3-" in host):
        bucket_name = host.split(".s3", 1)[0]
        object_key = path
    # path-style
    elif host in ("s3.amazonaws.com",) or (
        host.startswith("s3-") and host.endswith(".amazonaws.com")
    ):
        parts = path.split("/", 1)
        if len(parts) == 2:
            bucket_name, object_key = parts

    if not bucket_name or not object_key:
        logger.debug("Unable to parse S3 bucket/key from URL: %s", url)
        return None, None
    return bucket_name, object_key


def __build_cache_key_name_for_asset(url: str, expiration: int, inline: bool) -> str:
    suffix = "inline" if inline else "download"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"presign:{expiration}:{suffix}:{url_hash}"


def generate_presigned_urls(
    asset_urls: List[str],
    url_expiration: int = DEFAULT_PRESIGNED_URL_TTL,
    force_download: bool = True,
    max_workers: int = 5,  # kept for signature compatibility
) -> Dict[str, str]:
    """
    Batch presign with cache. No duplicate work.
    """
    # Get pre-signed url from cache
    request_inline_url = not force_download
    asset_url_to_cache_key_map: Dict[str, str] = {}
    for asset_url in asset_urls:
        if asset_url:
            asset_url_to_cache_key_map[asset_url] =  __build_cache_key_name_for_asset(asset_url, url_expiration, request_inline_url)  
    
    cache_keys: List[str] = list(asset_url_to_cache_key_map.values())
    presigned_urls_in_cache = cache.get_many(cache_keys)

    asset_url_to_presigned_url_map: Dict[str, str] = {}
    for asset_url, cache_key in asset_url_to_cache_key_map.items():
        if cache_key in presigned_urls_in_cache:
            asset_url_to_presigned_url_map[asset_url] = str(presigned_urls_in_cache[cache_key])

    # Generate new pre-signed url for remaining assets
    asset_urls_not_in_cache = [asset_url for asset_url in asset_urls if asset_url and asset_url not in asset_url_to_presigned_url_map]
    for asset_url in asset_urls_not_in_cache:
        presigned_url = __generate_single_presigned_url(asset_url, url_expiration, force_download)
        if presigned_url:
            asset_url_to_presigned_url_map[asset_url] = presigned_url

    if asset_url_to_presigned_url_map:
        cache.set_many({asset_url_to_cache_key_map[asset_url]: presigned_url for asset_url, presigned_url in asset_url_to_presigned_url_map.items()}, timeout=url_expiration)
    
    return asset_url_to_presigned_url_map


# -------- helpers --------
def __generate_single_presigned_url(
    url: str, expiration: int, force_download: bool
) -> Optional[str]:
    b, k = _parse_s3_url(url)
    if not b or not k:
        return None

    params = {"Bucket": b, "Key": k}
    if force_download:
        _apply_force_download(params, k)

    try:
        return s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params=params,
            ExpiresIn=expiration,
        )
    except ClientError as e:
        logger.warning("Presign error for %s: %s", url, e)
        return None


def _apply_force_download(params: dict, key: str) -> None:
    filename = key.rsplit("/", 1)[-1].lower()
    if any(filename.endswith(ext) for ext in _FORCE_DOWNLOAD_EXTENSIONS):
        params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'


def generate_inline_presigned_urls(
    urls: List[str], expiration: int = DEFAULT_PRESIGNED_URL_TTL
) -> Dict[str, str]:
    """
    Inline presigns without pre-checking existence (avoids extra S3 API calls).
    """
    out: Dict[str, str] = {}
    for u in urls:
        if not u:
            continue
        ck = __build_cache_key_name_for_asset(u, expiration, inline=True)
        cached = cache.get(ck)
        if cached:
            out[u] = cached
            continue

        b, k = _parse_s3_url(u)
        if not b or not k:
            continue
        try:
            signed = s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": b, "Key": k, "ResponseContentDisposition": "inline"},
                ExpiresIn=expiration,
            )
            out[u] = signed
            cache.set(ck, signed, timeout=expiration)
        except ClientError as e:
            logger.warning("Inline presign error for %s: %s", u, e)
    return out
