import boto3
from django.conf import settings

s3_client = boto3.client("s3")
S3_EXPECTED_OWNER = getattr(settings, "AWS_EXPECTED_BUCKET_OWNER", None)

# ExpectedBucketOwner isnt supported by all methods, leave it out
UNSUPPORTED_METHODS = {"download_fileobj"}


def s3_call(method: str, **kwargs):
    if S3_EXPECTED_OWNER and method not in UNSUPPORTED_METHODS:
        kwargs.setdefault("ExpectedBucketOwner", S3_EXPECTED_OWNER)
    return getattr(s3_client, method)(**kwargs)
