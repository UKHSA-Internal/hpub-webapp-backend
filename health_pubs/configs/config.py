import logging

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class AWSClients:
    _instance = None
    _secrets_manager_client = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(AWSClients, cls).__new__(cls)
        return cls._instance

    @property
    def secrets_manager_client(self):
        if self._secrets_manager_client is None:
            self._secrets_manager_client = boto3.client(
                "secretsmanager", region_name="eu-west-2"
            )
        return self._secrets_manager_client


aws_clients = AWSClients()


def get_secret_value(secret_id):
    """Fetch the secret value from AWS Secrets Manager."""
    try:
        client = aws_clients.secrets_manager_client
        response = client.get_secret_value(SecretId=secret_id)

        # Check if the secret is a string or binary
        if "SecretString" in response:
            return response["SecretString"]
        elif "SecretBinary" in response:
            # For binary secrets, decode to a string format
            return response["SecretBinary"].decode("utf-8")
        else:
            raise ValueError("SecretString and SecretBinary are undefined")
    except ClientError:
        raise Exception("Failed to retrieve secret from Secrets Manager.")


#
