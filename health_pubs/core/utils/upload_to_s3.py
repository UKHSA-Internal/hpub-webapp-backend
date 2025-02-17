import os
from venv import logger

import boto3
import config
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
import logging

logger = logging.getLogger(__name__)


def upload_file_to_s3(file_name: str, bucket: str, object_name: str = None):
    """Upload a file to an S3 bucket."""
    s3_client = boto3.client("s3", endpoint_url=config.AWS_ENDPOINT_URL_S3)

    if object_name is None:
        object_name = file_name

    # Check if the file exists
    if not os.path.exists(file_name):
        logger.info(f"The file {file_name} does not exist.")
        return False

    try:
        s3_client.upload_file(file_name, bucket, object_name)
    except FileNotFoundError:
        logger.info(f"The file {file_name} was not found.")
        return False
    except NoCredentialsError:
        logger.info("Credentials not available.")
        return False
    except PartialCredentialsError:
        logger.info("Incomplete credentials provided.")
        return False
    except ClientError as e:
        logger.info(f"Unexpected error: {e}")
        return False

    logger.info(f"File {file_name} uploaded to {bucket}/{object_name}.")
    return True


# Example usage
if __name__ == "__main__":
    # Replace these with your own values
    # Path to the file you want to upload
    file_name = "/home/ebubeoguchi/hpub-webapp/hpub-backend/health_pubs/core/utils/audio_transcript.txt"
    bucket_name = "hpub-publications-media-dev"  # Your S3 bucket name
    object_name = (
        "audio_transcript.txt"  # The name that will be used for the file in S3
    )

    # Call the function to upload the file
    upload_file_to_s3(file_name, bucket_name, object_name)
