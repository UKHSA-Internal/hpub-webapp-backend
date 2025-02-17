import os
import sys

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

import logging

import requests
import config

# Load the configuration module

logger = logging.getLogger(__name__)

def get_oauth_token():
    data = {
        "grant_type": "client_credentials",
        "client_id": config.OS_ADDRESS_VERIFICATION_CLIENT_ID,
        "client_secret": config.OS_ADDRESS_VERIFICATION_API_KEY,
        "scope": config.OS_ADDRESS_VERIFICATION_CLIENT_SCOPE,
    }
    response = requests.post(config.OS_ADDRESS_VERIFICATION_TOKEN_URL, data=data)
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

    match_address_url = f"{config.HPUB_FRONTEND_URL}/matchAddress"
    match_response = requests.post(
        match_address_url, json=match_address_payload, headers=headers
    )

    if match_response.status_code == 200:
        matched_addresses = match_response.json().get("matchedAddresses", [])
        if matched_addresses:
            address_instance.verified = True
    else:
        logger.warning("Failed to verify address: %s", match_response.json())
