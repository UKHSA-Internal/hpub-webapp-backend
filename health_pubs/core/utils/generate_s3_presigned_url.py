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

DEFAULT_PRESIGNED_URL_TTL = getattr(settings, "PRESIGNED_URL_TTL", 60*60*1) # Defaults to 1 hour
MINIMUM_PRESIGNED_URL_TTL = getattr(settings, "MINIMUM_PRESIGNED_URL_TTL", 60*30) # Defaults to 30 minutes

def _get_cache_timeout_in_ms(presigned_url_expiration_ms: int):
    if presigned_url_expiration_ms > MINIMUM_PRESIGNED_URL_TTL:
        return int(presigned_url_expiration_ms - MINIMUM_PRESIGNED_URL_TTL)
    # A value of 0 causes keys to immediately expire (effectively “don’t cache”).
    return 0


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


def _cache_key_for(url: str, expiration: int, inline: bool) -> str:
    suffix = "inline" if inline else "download"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"presign:{expiration}:{suffix}:{url_hash}"


def generate_presigned_urls(
    urls: List[str],
    expiration: int = DEFAULT_PRESIGNED_URL_TTL,
    force_download: bool = True,
    max_workers: int = 5,  # kept for signature compatibility
) -> Dict[str, str]:
    """
    Batch presign with cache. No duplicate work.
    """
    key_map = {
        u: _cache_key_for(u, expiration, inline=not force_download) for u in urls if u
    }
    existing = cache.get_many(list(key_map.values()))
    out: Dict[str, str] = {
        u: existing[ck] for u, ck in key_map.items() if ck in existing
    }

    to_sign = [u for u in urls if u and u not in out]
    for u in to_sign:
        signed = _presign_single_url(u, expiration, force_download)
        if signed:
            out[u] = signed

    if out:
        cache.set_many({key_map[u]: s for u, s in out.items()}, timeout=_get_cache_timeout_in_ms(expiration))
    return out


# -------- helpers --------
def _presign_single_url(
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
        ck = _cache_key_for(u, expiration, inline=True)
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
