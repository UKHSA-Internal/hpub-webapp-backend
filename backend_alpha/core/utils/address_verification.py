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
    match_address_payload = {
        "operationId": "matchAddress",
        "callingApplication": "HPUB",
        "address": full_address.strip(", "),
        "maxResults": 10,
        "fuzzy": True,
    }

    token = get_oauth_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "PythonDevApplication",
    }

    match_address_url = f"{base_url}/matchAddress"
    match_response = requests.post(
        match_address_url, json=match_address_payload, headers=headers
    )

    if match_response.status_code == 200:
        matched_addresses = match_response.json().get("matchedAddresses", [])
        if matched_addresses:
            address_instance.verified = True
    else:
        logger.warning("Failed to verify address: %s", match_response.json())
