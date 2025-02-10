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
        logger.debug(f"Retrieving secret for {secret_id}")
        response = client.get_secret_value(SecretId=secret_id)

        # Check if the secret is a string or binary
        if "SecretString" in response:
            logger.debug(f"SecretString retrieved for {secret_id}")
            return response["SecretString"]
        elif "SecretBinary" in response:
            logger.debug(f"SecretBinary retrieved for {secret_id}")
            # For binary secrets, decode to a string format
            return response["SecretBinary"].decode("utf-8")
        else:
            raise ValueError("SecretString and SecretBinary are undefined")
    except ClientError as e:
        logger.error(f'Error retrieving secret: {e.response["Error"]["Message"]}')
        error_response = {
            "Error": {
                "Code": "SecretRetrievalError",
                "Message": f'Error retrieving secret: {e.response["Error"]["Message"]}'
            }
        }
        raise ClientError(error_response, "GetSecretValue")


#
