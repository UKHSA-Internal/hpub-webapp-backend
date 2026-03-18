import os
from typing import Optional

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError
from django.conf import settings

from core.utils import logging_utils


S3_EXPECTED_OWNER = getattr(settings, "AWS_EXPECTED_BUCKET_OWNER", None)


logger = logging_utils.get_logger(__name__)
s3_client = boto3.client("s3")


def __s3_call(method: str, **kwargs):
    # ExpectedBucketOwner isnt supported by all methods, leave it out
    if S3_EXPECTED_OWNER and method not in {"download_fileobj"}:
        kwargs.setdefault("ExpectedBucketOwner", S3_EXPECTED_OWNER)
    return getattr(s3_client, method)(**kwargs)


def get_head_object(**kwargs):
    return __s3_call("head_object", **kwargs)


def get_object(**kwargs):
    return __s3_call("get_object", **kwargs)


def download_file_object(**kwargs):
    return __s3_call("download_fileobj", **kwargs)


def upload_file_object(file_name: str, bucket: str, object_name: Optional[str] = None):
    """Upload a file to an S3 bucket."""
    if object_name is None:
        object_name = file_name

    # Check if the file exists
    if not os.path.exists(file_name):
        logger.info(f"The file {file_name} does not exist.")
        return False

    try:
        __s3_call('upload_file',file_name=file_name, bucket=bucket, object_name=object_name)
        logger.info(f"File {file_name} uploaded to {bucket}/{object_name}.")
        return True
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
