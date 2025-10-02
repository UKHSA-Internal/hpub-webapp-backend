# core/utils/s3_safe.py
import boto3
from django.conf import settings

s3_client = boto3.client("s3")
S3_EXPECTED_OWNER = getattr(settings, "AWS_EXPECTED_BUCKET_OWNER", None)


def s3_call(method: str, **kwargs):
    if S3_EXPECTED_OWNER:
        kwargs.setdefault("ExpectedBucketOwner", S3_EXPECTED_OWNER)
    return getattr(s3_client, method)(**kwargs)
