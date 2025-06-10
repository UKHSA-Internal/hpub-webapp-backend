import base64
import json
import logging
import os
import sys
from typing import Optional, List

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.utils.config_loader import load_environment

from .config import get_secret_value

load_environment()


logger = logging.getLogger(__name__)

RSA_KEYS_SECRET_ID_ERROR_MSG = "RSA_KEYS_SECRET_ID is not set in the environment."
DEV_ORIGINS = [
    "http://localhost:3000",  # NOSONAR: safe in local dev only
    "http://localhost:5173",  # NOSONAR: safe in local dev only
    "http://127.0.0.1:5173",  # NOSONAR: safe in local dev only
]


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
    def _parse_json(json_string: str, key: Optional[str] = None) -> str:
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
    def _secure(origin: str) -> str:
        """Force HTTPS on any HTTP URL, leave HTTPS ones alone."""
        return origin.replace("http://", "https://")  # NOSONAR

    @staticmethod
    def get_django_debug_value() -> bool:
        """
        Returns True if DJANGO_DEBUG is set to a truthy string ("1", "true", "yes").
        """
        raw = Config.get_value("DJANGO_DEBUG", is_secret=False)
        return raw.lower() in ("1", "true", "yes")

    @staticmethod
    def get_django_allowed_hosts() -> List[str]:
        """
        Returns ALLOWED_HOSTS from env (comma-separated), or [] if unset.
        """
        try:
            raw = Config.get_value("DJANGO_ALLOWED_HOSTS", is_secret=False)
        except EnvironmentError:
            return []
        return [h.strip() for h in raw.split(",") if h.strip()]

    @staticmethod
    def get_csrf_trusted_origins() -> List[str]:
        """
        Returns CSRF_TRUSTED_ORIGINS (comma-separated), forcing HTTPS if not DEBUG.
        """
        try:
            raw = Config.get_value("CSRF_TRUSTED_ORIGINS", is_secret=False)
        except EnvironmentError:
            return []
        debug = Config.get_django_debug_value()
        origins: List[str] = []
        for o in raw.split(","):
            o = o.strip()
            if not o:
                continue
            origins.append(o if debug else Config._secure(o))
        return origins

    @staticmethod
    def get_cors_allowed_origins() -> List[str]:
        """
        If DEBUG: allow DEV_ORIGINS + HPUB_FRONTEND_URL as-is.
        Else: only HPUB_FRONTEND_URL, forced to HTTPS.
        """
        debug = Config.get_django_debug_value()
        try:
            hpub = Config.get_value("HPUB_FRONTEND_URL", is_secret=False)
        except EnvironmentError:
            hpub = None

        if debug:
            allowed = list(DEV_ORIGINS)
            if hpub:  # still guard just in case
                allowed.append(hpub)
        else:
            allowed = []
            if hpub:
                allowed.append(Config._secure(hpub))

        # dedupe preserving order
        seen = set()
        result: List[str] = []
        for url in allowed:
            if url and url not in seen:
                seen.add(url)
                result.append(url)
        return result

    @staticmethod
    def get_aps_api_key():
        """Retrieve the APS API key from secrets manager."""
        aps_api_key = Config.get_value("APS_API_KEY", is_secret=False)
        return aps_api_key

    @staticmethod
    def get_gov_uk_notify_api_key():
        """Retrieve the GOV.UK Notify API key from environment or secrets manager."""
        return Config.get_value("GOV_UK_NOTIFY_API_KEY", is_secret=False)

    @staticmethod
    def get_address_verify_api_key():
        """Retrieve the address verification API key from environment or secrets manager."""
        return Config.get_value("OS_ADDRESS_VERIFICATION_API_KEY", is_secret=False)

    @staticmethod
    def get_address_verify_client_id():
        """Retrieve the address verification Client Id from environment or secrets manager."""
        return Config.get_value("OS_ADDRESS_VERIFICATION_CLIENT_ID", is_secret=False)

    @staticmethod
    def get_address_verify_client_scope():
        """Retrieve the address verification Client Scope from environment or secrets manager."""
        return Config.get_value("OS_ADDRESS_VERIFICATION_CLIENT_SCOPE", is_secret=False)

    @staticmethod
    def get_non_secret_value(key: str):
        """Fetch non-secret value from environment (e.g., .env file)."""
        return Config.get_value(key, is_secret=False)

    @staticmethod
    def get_gov_uk_notify_email_template_id():
        return Config.get_value("GOV_UK_NOTIFY_EMAIL_TEMPLATE_ID", is_secret=False)

    @staticmethod
    def get_gov_uk_notify_contact_us_email_template_id():
        return Config.get_value("CONTACT_US_TEMPLATE_ID", is_secret=False)

    @staticmethod
    def get_gov_uk_notify_contact_us_email_address():
        return Config.get_value("CONTACT_US_APS_EMAIL_ADDRESS", is_secret=False)

    @staticmethod
    def get_gov_uk_notify_sms_template_id():
        return Config.get_value("GOV_UK_NOTIFY_SMS_TEMPLATE_ID", is_secret=False)

    @staticmethod
    def get_gov_uk_notify_api_url():
        return Config.get_value("GOV_UK_NOTIFY_API_URL", is_secret=False)

    @staticmethod
    def get_gov_uk_notify_unsubscribe_url():
        return Config.get_value("GOV_UK_NOTIFY_UNSUBSCRIBE_URL", is_secret=False)

    @staticmethod
    def get_aps_test_base_url():
        return Config.get_value("APS_TEST_BASE_URL", is_secret=False)

    @staticmethod
    def get_azure_b2c_secret_id():
        return Config.get_value("AZURE_B2C_CLIENT_SECRET_ID", is_secret=False)

    @staticmethod
    def get_azure_b2c_client_id():
        return Config.get_value("AZURE_B2C_CLIENT_ID", is_secret=False)

    @staticmethod
    def get_azure_b2c_tenant_id():
        return Config.get_value("AZURE_B2C_TENANT_ID", is_secret=False)

    @staticmethod
    def get_azure_b2c_tenant_name():
        return Config.get_value("AZURE_B2C_TENANT_NAME", is_secret=False)

    @staticmethod
    def get_azure_b2c_policy_name():
        return Config.get_value("AZURE_B2C_POLICY_NAME", is_secret=False)

    @staticmethod
    def get_azure_b2c_jwks_uri():
        return Config.get_value("AZURE_B2C_JWKS_URI", is_secret=False)

    @staticmethod
    def get_azure_b2c_issuer():
        return Config.get_value("AZURE_B2C_ISSUER", is_secret=False)

    @staticmethod
    def get_address_verify_base_url():
        return Config.get_value("OS_ADDRESS_VERIFICATION_BASE_URL", is_secret=False)

    @staticmethod
    def get_address_verify_token_url():
        return Config.get_value("OS_ADDRESS_VERIFICATION_TOKEN_URL", is_secret=False)

    @staticmethod
    def get_hpub_base_api_url():
        return Config.get_value("HPUB_FRONTEND_URL", is_secret=False)

    @staticmethod
    def get_hpub_event_bridge_source():
        return Config.get_value("HPUB_EVENT_BRIDGE_SOURCE", is_secret=False)

    @staticmethod
    def get_hpub_event_bridge_bus_name():
        return Config.get_value("HPUB_EVENT_BRIDGE_BUS_NAME", is_secret=False)

    @staticmethod
    def get_hpub_event_bridge_detail_type_order_creation():
        return Config.get_value(
            "HPUB_EVENT_BRIDGE_DETAIL_TYPE_ORDER_CREATION", is_secret=False
        )

    @staticmethod
    def get_hpub_event_bridge_detail_type_product_draft():
        return Config.get_value(
            "HPUB_EVENT_BRIDGE_DETAIL_TYPE_PRODUCT_DRAFT", is_secret=False
        )

    @staticmethod
    def get_hpub_event_bridge_detail_type_product_archive():
        return Config.get_value(
            "HPUB_EVENT_BRIDGE_DETAIL_TYPE_PRODUCT_ARCHIVE", is_secret=False
        )

    @staticmethod
    def get_hpub_event_bridge_detail_type_product_withdrawn():
        return Config.get_value(
            "HPUB_EVENT_BRIDGE_DETAIL_TYPE_PRODUCT_WITHDRAWN", is_secret=False
        )

    @staticmethod
    def get_hpub_event_bridge_detail_type_product_live():
        return Config.get_value(
            "HPUB_EVENT_BRIDGE_DETAIL_TYPE_PRODUCT_LIVE", is_secret=False
        )

    @staticmethod
    def get_hpub_s3_bucket_name():
        return Config.get_value("VITE_BUCKET_NAME", is_secret=False)

    @staticmethod
    def get_django_secret_key():
        return Config.get_value("DJANGO_SECRET_KEY", is_secret=False)

    @staticmethod
    def _decode_rsa_key(encoded_key: str) -> str:
        """
        Decodes a Base64-encoded RSA key back to PEM format.
        """
        try:
            decoded_key = base64.b64decode(encoded_key).decode("utf-8")
            logger.debug("RSA key decoded successfully.")
            return decoded_key
        except Exception as e:
            logger.error(f"Failed to decode RSA key: {e}")
            raise

    @staticmethod
    def get_rsa_private_key():
        """Retrieve and decode the RSA private key from environment variables."""
        encoded_key = Config.get_value("RSA_PRIVATE_KEY", is_secret=False)
        return Config._decode_rsa_key(encoded_key)

    @staticmethod
    def get_rsa_public_key():
        """Retrieve and decode the RSA public key from environment variables."""
        encoded_key = Config.get_value("RSA_PUBLIC_KEY", is_secret=False)
        return Config._decode_rsa_key(encoded_key)

    @staticmethod
    def get_db_port():
        return Config.get_value("DB_PORT", is_secret=False)

    @staticmethod
    def get_db_user():
        return Config.get_value("DB_USER", is_secret=False)

    @staticmethod
    def get_db_password():
        return Config.get_value("DB_PASSWORD", is_secret=False)

    @staticmethod
    def get_db_host():
        return Config.get_value("DB_HOST", is_secret=False)

    @staticmethod
    def get_db_name():
        return Config.get_value("DB_NAME", is_secret=False)


#
