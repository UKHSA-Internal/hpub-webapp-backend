import json
import logging
import os
import re
import sys
from typing import Optional

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.utils.config_loader import load_environment

from .config import get_secret_value

load_environment()


logger = logging.getLogger(__name__)


class Config:
    """Class to retrieve and parse database connection information and other configurations."""

    @staticmethod
    def _get_value(key: str, is_secret: bool = False) -> str:
        """
        Retrieve the specified environment variable or secret.

        :param key: The name of the environment variable or secret.
        :param is_secret: Whether the value is a secret and needs additional fetching.
        :return: The retrieved value.
        :raises EnvironmentError: If the key is undefined or empty.
        """
        value = os.environ.get(key)
        if is_secret:
            secret_value = Config._fetch_secret_or_local(value)
            if secret_value:
                value = Config._parse_json(secret_value, key)
            else:
                logger.error(f"Secret value for {key} is empty.")
                raise ValueError(f"Secret value for {key} is empty.")
        if not value:
            logger.error(f"Environment variable {key} is undefined or empty")
            raise EnvironmentError(f"Environment variable {key} is undefined or empty")
        return value

    @staticmethod
    def _fetch_secret_or_local(key: str) -> Optional[str]:
        """
        Fetch secret from AWS Secrets Manager or local secrets file based on environment.

        :param key: The name of the secret to retrieve.
        :return: The secret value, or None if not found.
        :raises FileNotFoundError: If the local secrets file is not found in development.
        :raises ValueError: If the local secrets file is not valid JSON.
        """
        if key == "AZURE_B2C_CLIENT_ID":
            pass
        else:
            logger.info(f"Fetching {key} from AWS Secrets Manager.")
            return get_secret_value(key)


    @staticmethod
    def _parse_json(json_string: str, key: str or None = None) -> str:
        """Parse the JSON string and extract the value."""
        try:
            # Convert the JSON string into a Python dictionary
            parsed_json = json.loads(json_string)
            # Return the value (assumes you want the first key-value pair)
            if key and key in parsed_json:
                return parsed_json[key]
            return next(iter(parsed_json.values()), None)  # Get the first value
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON string: {e}")
            raise ValueError("Invalid JSON format for secret value")

    @staticmethod
    def get_value(key: str, is_secret: bool = False):
        """Retrieve the specified environment variable, handling errors and logging."""
        value = Config._get_value(key, is_secret)
        if value is None:
            logger.error(f"Environment variable {key} is undefined or empty")
            raise EnvironmentError(f"Environment variable {key} is undefined or empty")
        # for debugging purposes
        logger.debug(f"Environment variable {key} retrieved successfully.")
        return value

    @staticmethod
    def get_aps_api_key():
        """Retrieve the APS API key from secrets manager."""
        aps_api_key = Config.get_value("APS_API_KEY", is_secret=True)
        return aps_api_key

    @staticmethod
    def get_gov_uk_notify_api_key():
        """Retrieve the GOV.UK Notify API key from environment or secrets manager."""
        return Config.get_value("GOV_UK_NOTIFY_API_KEY", is_secret=True)

    @staticmethod
    def get_address_verify_api_key():
        """Retrieve the address verification API key from environment or secrets manager."""
        return Config.get_value("OS_ADDRESS_VERIFICATION_API_KEY", is_secret=True)

    @staticmethod
    def get_address_verify_client_id():
        """Retrieve the address verification Client Id from environment or secrets manager."""
        return Config.get_value("OS_ADDRESS_VERIFICATION_CLIENT_ID", is_secret=True)

    @staticmethod
    def get_address_verify_client_scope():
        """Retrieve the address verification Client Scope from environment or secrets manager."""
        return Config.get_value("OS_ADDRESS_VERIFICATION_CLIENT_SCOPE", is_secret=True)

    @staticmethod
    def get_non_secret_value(key: str):
        """Fetch non-secret value from environment (e.g., .env file)."""
        return Config.get_value(key, is_secret=False)

    @staticmethod
    def get_gov_uk_notify_email_template_id():
        return Config.get_value("GOV_UK_NOTIFY_EMAIL_TEMPLATE_ID", is_secret=True)

    @staticmethod
    def get_gov_uk_notify_contact_us_email_template_id():
        return Config.get_value("CONTACT_US_TEMPLATE_ID", is_secret=True)

    @staticmethod
    def get_gov_uk_notify_contact_us_email_address():
        return Config.get_value("CONTACT_US_APS_EMAIL_ADDRESS", is_secret=True)

    @staticmethod
    def get_gov_uk_notify_sms_template_id():
        return Config.get_value("GOV_UK_NOTIFY_SMS_TEMPLATE_ID", is_secret=True)

    @staticmethod
    def get_gov_uk_notify_api_url():
        return Config.get_value("GOV_UK_NOTIFY_API_URL", is_secret=True)

    @staticmethod
    def get_gov_uk_notify_unsubscribe_url():
        return Config.get_value("GOV_UK_NOTIFY_UNSUBSCRIBE_URL", is_secret=True)

    @staticmethod
    def get_aps_test_base_url():
        return Config.get_value("APS_TEST_BASE_URL", is_secret=True)

    @staticmethod
    def get_azure_b2c_secret_id():
        return Config.get_value("AZURE_B2C_CLIENT_SECRET_ID", is_secret=True)

    @staticmethod
    def get_azure_b2c_client_id():
        return Config.get_value("AZURE_B2C_CLIENT_ID", is_secret=True)

    @staticmethod
    def get_azure_b2c_tenant_id():
        return Config.get_value("AZURE_B2C_TENANT_ID", is_secret=True)

    @staticmethod
    def get_azure_b2c_tenant_name():
        return Config.get_value("AZURE_B2C_TENANT_NAME", is_secret=True)

    @staticmethod
    def get_azure_b2c_policy_name():
        return Config.get_value("AZURE_B2C_POLICY_NAME", is_secret=True)

    @staticmethod
    def get_azure_b2c_jwks_uri():
        return Config.get_value("AZURE_B2C_JWKS_URI", is_secret=True)

    @staticmethod
    def get_azure_b2c_issuer():
        return Config.get_value("AZURE_B2C_ISSUER", is_secret=True)

    @staticmethod
    def get_address_verify_base_url():
        return Config.get_value("OS_ADDRESS_VERIFICATION_BASE_URL", is_secret=True)

    @staticmethod
    def get_address_verify_token_url():
        return Config.get_value("OS_ADDRESS_VERIFICATION_TOKEN_URL", is_secret=True)

    @staticmethod
    def get_hpub_base_api_url():
        return Config.get_value("HPUB_FRONTEND_URL", is_secret=True)

    @staticmethod
    def get_django_secret_key():
        return Config.get_value("DJANGO_SECRET_KEY", is_secret=True)

    @staticmethod
    def get_postgres_connection_regex():
        """Retrieve PostgreSQL connection regex from secrets manager."""
        pattern = Config.get_value("POSTGRES_CONNECTION_REGEX", is_secret=True)
        if not pattern:
            raise ValueError("POSTGRES_CONNECTION_REGEX is not defined or empty.")
        return pattern

    @staticmethod
    def get_rsa_private_key():
        """Retrieve the RSA private key from AWS Secrets Manager."""
        secret_data = get_secret_value("hpub/rsa/keys")
        # Parse the JSON to extract the private key value
        private_key_data = json.loads(secret_data)
        return private_key_data["RSA_PRIVATE_KEY"]

    @staticmethod
    def get_rsa_public_key():
        """Retrieve the RSA public key from AWS Secrets Manager."""
        secret_data = get_secret_value("hpub/rsa/keys")
        # Parse the JSON to extract the public key value
        public_key_data = json.loads(secret_data)
        return public_key_data["RSA_PUBLIC_KEY"]

    @staticmethod
    def parse_connection_string(connection_string: str):
        """Parse PostgreSQL connection string and extract components."""
        try:
            # Fetch the regex pattern
            pattern = Config.get_postgres_connection_regex()

            # Use the pattern in `re.match`
            match = re.match(pattern, connection_string)
            if not match:
                logger.error(f"Invalid connection string format: {connection_string}")
                raise ValueError(
                    f"Invalid connection string format: {connection_string}"
                )
            return match.groupdict()
        except Exception as e:
            logger.error(f"Error parsing connection string: {e}")
            raise

    @property
    def db_connection_details(self):
        """
        Retrieve and parse the PostgreSQL connection string (stored as a secret).
        Storing the entire connection string as a single secret simplifies management and retrieval.
        Avoids the complexity of handling multiple secrets for each component.
        """
        connection_string = self.get_value(
            "HPUB_POSTGRES_CONNECTION_STRING", is_secret=True
        )

        # Parse the connection string directly since it's a plain string
        try:
            return self.parse_connection_string(connection_string)
        except ValueError as e:
            logger.error(f"Error extracting connection string: {e}")
            raise ValueError("Invalid format for connection string data")

    @property
    def DB_NAME(self):
        return self.db_connection_details["dbname"]

    @property
    def DB_USER(self):
        return self.db_connection_details["user"]

    @property
    def DB_PASSWORD(self):
        return self.db_connection_details["password"]

    @property
    def DB_HOST(self):
        return self.db_connection_details["host"]

    @property
    def DB_PORT(self):
        return self.db_connection_details["port"]
