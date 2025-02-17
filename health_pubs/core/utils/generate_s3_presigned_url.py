import logging
from typing import Dict, List
from urllib.parse import urlparse
import config

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError

# Setup logger
logger = logging.getLogger(__name__)


def generate_presigned_urls(urls: List[str], expiration: int = 3600) -> Dict[str, str]:
    """Generate pre-signed URLs for a list of S3 object URLs and return as a dictionary."""
    s3_client = boto3.client("s3",endpoint_url=config.AWS_ENDPOINT_URL_S3)
    presigned_urls = {}

    for url in urls:
        # Parse the bucket name and key from the URL
        parsed_url = urlparse(url)

        # Handle bucket names based on different S3 URL formats
        # This would need to be changed to handle localstack
        if "amazonaws.com" in parsed_url.netloc:
            # Standard S3 URL
            bucket_name = parsed_url.netloc.split(".")[0]
            object_key = parsed_url.path.lstrip("/")
        else:
            logging.info(f"Invalid S3 URL format: {url}")
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
