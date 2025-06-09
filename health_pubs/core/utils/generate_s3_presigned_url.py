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

# Instantiate a single S3 client at module level
s3_client = boto3.client("s3")

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
PRESIGNED_URL_TTL = getattr(settings, "PRESIGNED_URL_TTL")


def _parse_s3_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """(unchanged)"""
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path.lstrip("/")

    bucket_name = None
    object_key = None

    if host.endswith(".amazonaws.com") and (".s3." in host or ".s3-" in host):
        if ".s3." in host:
            bucket_name = host.split(".s3.", 1)[0]
        else:
            bucket_name = host.split(".s3-", 1)[0]
        object_key = path

    elif host == "s3.amazonaws.com" or (
        host.startswith("s3-") and host.endswith(".amazonaws.com")
    ):
        parts = path.split("/", 1)
        if len(parts) == 2:
            bucket_name, object_key = parts

    if not bucket_name or not object_key:
        logger.warning(f"Unable to parse S3 bucket/key from URL: {url}")
        return None, None

    return bucket_name, object_key


def _cache_key_for(original_url: str, expiration: int, inline: bool) -> str:
    """Make a unique cache key including expiration & disposition."""
    suffix = "inline" if inline else "download"
    return f"presign:{expiration}:{suffix}:{original_url}"


def generate_presigned_urls(
    urls: List[str],
    expiration: int = PRESIGNED_URL_TTL,  # Default 1 hour
    force_download: bool = True,
) -> Dict[str, str]:
    """
    Generate or fetch from cache presigned 'download' URLs for a list of S3 URLs.
    `expiration` seconds is also used as the cache TTL.
    """
    presigned: Dict[str, str] = {}

    for original_url in urls:
        cache_key = _cache_key_for(original_url, expiration, inline=not force_download)
        cached = cache.get(cache_key)
        if cached:
            presigned[original_url] = cached
            continue

        bucket, key = _parse_s3_url(original_url)
        if not bucket or not key:
            continue

        params = {"Bucket": bucket, "Key": key}
        if force_download:
            lower = key.lower()
            for ext in _FORCE_DOWNLOAD_EXTENSIONS:
                if lower.endswith(ext):
                    filename = key.rsplit("/", 1)[-1]
                    params[
                        "ResponseContentDisposition"
                    ] = f'attachment; filename="{filename}"'
                    break

        try:
            url = s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params=params,
                ExpiresIn=expiration,
            )
            presigned[original_url] = url
            cache.set(cache_key, url, timeout=expiration)

        except (NoCredentialsError, PartialCredentialsError) as cred_err:
            logger.error(f"Credentials error for {original_url}: {cred_err}")
        except ClientError as client_err:
            code = client_err.response.get("Error", {}).get("Code", "")
            logger.error(f"S3 ClientError ({code}) for {original_url}: {client_err}")
        except Exception as e:
            logger.error(f"Unexpected error for {original_url}: {e}")

    return presigned


def generate_inline_presigned_urls(
    urls: List[str],
    expiration: int = 3600,
) -> Dict[str, str]:
    """
    Generate or fetch from cache presigned 'inline' URLs for a list of S3 URLs.
    Verifies object existence before presigning.
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

        # verify existence
        try:
            s3_client.head_object(Bucket=bucket, Key=key)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey"):
                logger.warning(f"Missing S3 object: {bucket}/{key}")
            else:
                logger.warning(f"Head-object error for {bucket}/{key}: {e}")
            continue

        try:
            url = s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                    "ResponseContentDisposition": "inline",
                },
                ExpiresIn=expiration,
            )
            inline_map[original_url] = url
            cache.set(cache_key, url, timeout=expiration)

        except (NoCredentialsError, PartialCredentialsError) as cred_err:
            logger.error(f"Credentials error for inline {original_url}: {cred_err}")
        except ClientError as client_err:
            logger.error(f"S3 ClientError for inline {original_url}: {client_err}")

    return inline_map
