import os

import boto3
from botocore.exceptions import ClientError, NoCredentialsError, PartialCredentialsError


def upload_file_to_s3(file_name: str, bucket: str, object_name: str = None):
    """Upload a file to an S3 bucket."""
    s3_client = boto3.client("s3")

    if object_name is None:
        object_name = file_name

    # Check if the file exists
    if not os.path.exists(file_name):
        logging.info(f"The file {file_name} does not exist.")
        return False

    try:
        s3_client.upload_file(file_name, bucket, object_name)
    except FileNotFoundError:
        logging.info(f"The file {file_name} was not found.")
        return False
    except NoCredentialsError:
        logging.info("Credentials not available.")
        return False
    except PartialCredentialsError:
        logging.info("Incomplete credentials provided.")
        return False
    except ClientError as e:
        logging.info(f"Unexpected error: {e}")
        return False

    logging.info(f"File {file_name} uploaded to {bucket}/{object_name}.")
    return True


# Example usage
if __name__ == "__main__":
    # Replace these with your own values
    # Path to the file you want to upload
    file_name = "Partial Disruption Process Flow (Confluence Documentation)"
    bucket_name = "REDACTED_BUCKET_NAME"  # Your S3 bucket name
    object_name = (
        "audio_transcript.txt"  # The name that will be used for the file in S3
    )

    # Call the function to upload the file
    upload_file_to_s3(file_name, bucket_name, object_name)
