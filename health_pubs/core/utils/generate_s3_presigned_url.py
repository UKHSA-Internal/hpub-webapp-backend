import logging
from typing import Dict, List
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

# Setup logger
logger = logging.getLogger(__name__)


def generate_presigned_urls(urls: List[str], expiration: int = 3600) -> Dict[str, str]:
    """Generate pre-signed URLs for a list of S3 object URLs and return as a dictionary."""
    s3_client = boto3.client("s3")
    presigned_urls = {}

    for url in urls:
        # Parse the bucket name and key from the URL
        parsed_url = urlparse(url)

        # Handle bucket names based on different S3 URL formats
        if "amazonaws.com" in parsed_url.netloc:
            # Standard S3 URL
            bucket_name = parsed_url.netloc.split(".")[0]
            object_key = parsed_url.path.lstrip("/")
        else:
            logging.warning(f"Invalid S3 URL format: {url}")
            continue  # Skip to the next URL if the format is incorrect

        try:
            presigned_url = s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket_name, "Key": object_key},
                ExpiresIn=expiration,
            )
            # Add the original URL and presigned URL to the dictionary
            presigned_urls[url] = presigned_url
        except (NoCredentialsError, PartialCredentialsError) as e:
            logging.info(f"Error generating presigned URL for {url}: {e}")
        except ClientError as e:
            logging.info(f"Client error occurred for {url}: {e}")
    # logging.info("Presigned Url", presigned_urls)

    return presigned_urls


def generate_inline_presigned_urls(urls: list, expiration: int = 3600) -> dict:
    """
    For a list of S3 URLs, generate presigned URLs with an inline content disposition.
    This header tells browsers to render (for example, display a PDF inline in a new tab).
    Before generating the URL, the function checks that the S3 object exists.
    """
    s3_client = boto3.client("s3")
    inline_urls = {}
    for url in urls:
        parsed_url = urlparse(url)
        if "amazonaws.com" in parsed_url.netloc:
            bucket_name = parsed_url.netloc.split(".")[0]
            object_key = parsed_url.path.lstrip("/")
        else:
            logger.warning(f"Invalid S3 URL format: {url}")
            continue

        # Check if the object exists before generating the presigned URL.
        try:
            s3_client.head_object(Bucket=bucket_name, Key=object_key)
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ["404", "NoSuchKey"]:
                logger.warning(f"The specified key does not exist: {object_key}")
                continue
            else:
                logger.warning(f"Error checking existence of {object_key}: {e}")
                continue

        try:
            inline_url = s3_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": bucket_name,
                    "Key": object_key,
                    "ResponseContentDisposition": "inline",
                },
                ExpiresIn=expiration,
            )
            inline_urls[url] = inline_url
        except (NoCredentialsError, PartialCredentialsError) as e:
            logger.info(f"Credentials error generating inline URL for {url}: {e}")
        except ClientError as e:
            logger.info(f"Client error generating inline URL for {url}: {e}")

    return inline_urls


#
