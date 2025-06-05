# health_pubs/core/utils/generate_s3_presigned_url.py

import logging
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

# Instantiate a single S3 client at module level to avoid reinitialization
s3_client = boto3.client("s3")

# Valid file extensions for forcing a download Content-Disposition header
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


def _parse_s3_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Given a URL, attempt to parse out the S3 bucket name and object key.
    Supports URLs of the form:
      - https://{bucket}.s3.amazonaws.com/{key}
      - https://s3.amazonaws.com/{bucket}/{key}
      - https://{bucket}.s3-{region}.amazonaws.com/{key}
    Returns (bucket_name, object_key) or (None, None) if parsing fails.
    """
    parsed = urlparse(url)
    host = parsed.netloc
    path = parsed.path.lstrip("/")

    bucket_name: Optional[str] = None
    object_key: Optional[str] = None

    # Case 1: bucket is part of the hostname, e.g. "bucket.s3.amazonaws.com"
    if (
        host.endswith(".s3.amazonaws.com")
        or ".s3-" in host
        and host.endswith(".amazonaws.com")
    ):
        # bucket.s3.amazonaws.com or bucket.s3-region.amazonaws.com
        bucket_name = host.split(".")[0]
        object_key = path

    # Case 2: "s3.amazonaws.com/bucket/key..." style
    elif host == "s3.amazonaws.com":
        parts = path.split("/", 1)
        if len(parts) == 2:
            bucket_name, object_key = parts[0], parts[1]

    # Invalid or unsupported format
    if not bucket_name or not object_key:
        logger.warning(f"Unable to parse S3 bucket/key from URL: {url}")
        return None, None

    return bucket_name, object_key


def generate_presigned_urls(urls: List[str], expiration: int = 3600) -> Dict[str, str]:
    """
    Generate pre-signed URLs for a list of S3 object URLs and return as a dictionary.
    Uses the module-level `s3_client` instead of reinitializing it on each call.
    """
    presigned_urls: Dict[str, str] = {}

    for original_url in urls:
        bucket_name, object_key = _parse_s3_url(original_url)
        if not bucket_name or not object_key:
            # Skip invalid URLs
            continue

        params = {"Bucket": bucket_name, "Key": object_key}

        # For certain file extensions, force download with a Content-Disposition header
        lower_key = object_key.lower()
        for ext in _FORCE_DOWNLOAD_EXTENSIONS:
            if lower_key.endswith(ext):
                filename = object_key.rsplit("/", 1)[-1]
                params[
                    "ResponseContentDisposition"
                ] = f'attachment; filename="{filename}"'
                break

        try:
            presigned_url = s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params=params,
                ExpiresIn=expiration,
            )
            presigned_urls[original_url] = presigned_url

        except (NoCredentialsError, PartialCredentialsError) as cred_err:
            logger.error(
                f"Credentials error generating presigned URL for {original_url}: {cred_err}"
            )
        except ClientError as client_err:
            error_code = client_err.response.get("Error", {}).get("Code", "")
            logger.error(
                f"ClientError generating presigned URL for {original_url}: {error_code} – {client_err}"
            )
        except Exception as e:
            logger.error(f"Unexpected error for {original_url}: {e}")

    return presigned_urls


def generate_inline_presigned_urls(
    urls: List[str], expiration: int = 3600
) -> Dict[str, str]:
    """
    For a list of S3 URLs, generate presigned URLs with inline content disposition
    (so browsers will try to display content inline). Before generating the URL,
    this function checks that the S3 object exists. Uses the module‐level `s3_client`.
    """
    inline_urls: Dict[str, str] = {}

    for url in urls:
        bucket_name, object_key = _parse_s3_url(url)
        if not bucket_name or not object_key:
            continue

        # Verify that the object actually exists
        try:
            s3_client.head_object(Bucket=bucket_name, Key=object_key)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ["404", "NoSuchKey"]:
                logger.warning(f"S3 object not found: {bucket_name}/{object_key}")
            else:
                logger.warning(
                    f"Error checking existence of {bucket_name}/{object_key}: {e}"
                )
            continue

        try:
            inline_url = s3_client.generate_presigned_url(
                ClientMethod="get_object",
                Params={
                    "Bucket": bucket_name,
                    "Key": object_key,
                    "ResponseContentDisposition": "inline",
                },
                ExpiresIn=expiration,
            )
            inline_urls[url] = inline_url

        except (NoCredentialsError, PartialCredentialsError) as cred_err:
            logger.error(
                f"Credentials error generating inline URL for {url}: {cred_err}"
            )
        except ClientError as client_err:
            logger.error(f"Client error generating inline URL for {url}: {client_err}")

    return inline_urls
