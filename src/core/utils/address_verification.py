import os
import sys


sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

import logging

import requests
from configs.get_secret_config import Config

# Load the configuration module

logger = logging.getLogger(__name__)

config = Config()

base_url = config.get_address_verify_base_url()
api_key = config.get_address_verify_api_key()
client_id = config.get_address_verify_client_id()
client_scope = config.get_address_verify_client_scope()
token_url = config.get_address_verify_token_url()


def get_oauth_token():
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": api_key,
        "scope": client_scope,
    }
    response = requests.post(token_url, data=data)
    response.raise_for_status()  # This will raise an error if the request fails
    token = response.json().get("access_token")

    return token


def verify_address(address_instance):
    """Call the matchAddress API to verify the address."""
    full_address = f"{address_instance.address_line1}, {address_instance.address_line2 or ''}, {address_instance.postcode}"

    payload = {
        "operationId": "matchAddress",
        "callingApplication": "HPUB",
        "address": full_address.strip(", "),
        "maxResults": 10,
        "fuzzy": True,
    }

    try:
        token = get_oauth_token()
    except Exception as e:
        logger.error("Failed to obtain OAuth token: %s", e)
        return False

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "PythonDevApplication",
    }

    try:
        resp = requests.post(
            f"{base_url}/matchAddress",
            json=payload,
            headers=headers,
            timeout=10,  # prevent hanging
        )
    except requests.RequestException as e:
        logger.error("Request to matchAddress failed: %s", e)
        return False

    if resp.status_code != 200:
        # Fallback if body is not JSON
        try:
            details = resp.json()
        except Exception:
            details = resp.text
        logger.warning(
            "Address verification failed (HTTP %s): %s",
            resp.status_code,
            str(details)[:500],
        )
        return False

    # Try parse JSON safely
    try:
        data = resp.json()
    except Exception:
        logger.error("Address verify API returned non-JSON: %s", resp.text[:200])
        return False

    matches = data.get("matchedAddresses", [])
    if not matches:
        logger.info("No matched addresses returned for %s", full_address)
        return False

    # Take first match and compare postcode
    match = matches[0]
    if (
        match
        and address_instance.postcode.strip().lower()
        == (match.get("postcode") or "").strip().lower()
    ):
        address_instance.verified = True
        return True

    return False
