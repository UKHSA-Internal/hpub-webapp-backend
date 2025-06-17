import hashlib
import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
from django.core.cache import cache
from django.conf import settings

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

# Single, module‐level S3 client
s3_client = boto3.client("s3")

# Force‐download file extensions
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

# Default TTL (in seconds) for presigned URLs
DEFAULT_PRESIGNED_URL_TTL = getattr(settings, "PRESIGNED_URL_TTL", 3600)


def _parse_s3_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Parse an S3 URL into (bucket_name, object_key). Returns (None, None) on failure.
    """
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path.lstrip("/")

    bucket_name = None
    object_key = None

    # Virtual‐hosted–style
    if host.endswith(".amazonaws.com") and ("s3." in host or "s3-" in host):
        # e.g. bucket.s3.region.amazonaws.com
        bucket_name = host.split(".s3", 1)[0]
        object_key = path

    # Path‐style
    elif host in ("s3.amazonaws.com",) or (
        host.startswith("s3-") and host.endswith(".amazonaws.com")
    ):
        parts = path.split("/", 1)
        if len(parts) == 2:
            bucket_name, object_key = parts

    if not bucket_name or not object_key:
        logger.warning("Unable to parse S3 bucket/key from URL: %s", url)
        return None, None

    return bucket_name, object_key


def _cache_key_for(url: str, expiration: int, inline: bool) -> str:
    """
    Generate a safe cache key by hashing the original URL.
    Format: presign:{ttl}:{inline|download}:{sha256(url)}
    """
    suffix = "inline" if inline else "download"
    url_hash = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return f"presign:{expiration}:{suffix}:{url_hash}"


def generate_presigned_urls(
    urls: List[str],
    expiration: int = DEFAULT_PRESIGNED_URL_TTL,
    force_download: bool = True,
) -> Dict[str, str]:
    """
    For each S3 URL in `urls`, return a presigned download URL.
    Caches each presigned URL under a key derived from a hash of the original URL.
    """
    presigned_map: Dict[str, str] = {}

    for original_url in urls:
        cache_key = _cache_key_for(original_url, expiration, inline=not force_download)
        cached = cache.get(cache_key)
        if cached:
            presigned_map[original_url] = cached
            continue

        bucket, key = _parse_s3_url(original_url)
        if not bucket or not key:
            # skip invalid URLs
            continue

        params = {"Bucket": bucket, "Key": key}
        if force_download:
            lower_key = key.lower()
            for ext in _FORCE_DOWNLOAD_EXTENSIONS:
                if lower_key.endswith(ext):
                    filename = key.rsplit("/", 1)[-1]
                    params[
                        "ResponseContentDisposition"
                    ] = f'attachment; filename="{filename}"'
                    break

        try:
            signed_url = s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params=params,
                ExpiresIn=expiration,
            )
            presigned_map[original_url] = signed_url
            cache.set(cache_key, signed_url, timeout=expiration)
        except (NoCredentialsError, PartialCredentialsError) as cred_err:
            logger.error("Credentials error for %s: %s", original_url, cred_err)
        except ClientError as client_err:
            code = client_err.response.get("Error", {}).get("Code", "")
            logger.error(
                "S3 ClientError (%s) for %s: %s", code, original_url, client_err
            )
        except Exception as e:
            logger.error("Unexpected error for %s: %s", original_url, e)

    return presigned_map


def generate_inline_presigned_urls(
    urls: List[str],
    expiration: int = DEFAULT_PRESIGNED_URL_TTL,
) -> Dict[str, str]:
    """
    For each S3 URL in `urls`, verify object exists then return a presigned inline URL.
    Caches each presigned URL under a key derived from a hash of the original URL.
    """
    inline_map: Dict[str, str] = {}

    for original_url in urls:
        cache_key = _cache_key_for(original_url, expiration, inline=True)
        cached = cache.get(cache_key)
        if cached:
            inline_map[original_url] = cached
            continue

        bucket, key = _parse_s3_url(original_url)
        if not bucket or not key:
            continue

        # Verify existence first
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
        except ClientError as head_err:
            code = head_err.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey"):
                logger.warning("Missing S3 object: %s/%s", bucket, key)
            else:
                logger.warning("Head-object error for %s/%s: %s", bucket, key, head_err)
            continue

        try:
            signed_url = s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "ResponseContentDisposition": "inline",
                },
                ExpiresIn=expiration,
            )
            inline_map[original_url] = signed_url
            cache.set(cache_key, signed_url, timeout=expiration)
        except (NoCredentialsError, PartialCredentialsError) as cred_err:
            logger.error("Credentials error for inline %s: %s", original_url, cred_err)
        except ClientError as client_err:
            code = client_err.response.get("Error", {}).get("Code", "")
            logger.error(
                "S3 ClientError (%s) for inline %s: %s", code, original_url, client_err
            )
        except Exception as e:
            logger.error("Unexpected inline error for %s: %s", original_url, e)

    return inline_map
