import msal
import requests
from rest_framework import status

from urllib.parse import quote
from requests import Response

from configs.get_secret_config import Config
from core.utils import logging_utils
from core.auth import services as auth_service 

config = Config()
TENANT_ID = config.get_azure_b2c_tenant_id()
TENANT_NAME = config.get_azure_b2c_tenant_name()
CLIENT_ID = config.get_azure_b2c_client_id()
CLIENT_SECRET = config.get_azure_b2c_secret_value()

logger = logging_utils.get_logger(__name__)

def __raise_for_status(response: Response):
    try:
        response.raise_for_status()
    except:
        error = response.json()
        logger.error(str(error))
        raise Exception(error)

def get_access_token():
    url = f"https://{TENANT_NAME}.ciamlogin.com/{TENANT_ID}/oauth2/v2.0/token"
    data = {
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "grant_type": "client_credentials",
        "scope": "https://graph.microsoft.com/.default",
    }
    response = requests.post(url, data=data)
    __raise_for_status(response)
    token_json = response.json()
    return token_json["access_token"]
    

def get_headers():
    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json"
    }
    return headers

def list_users():
    url = "https://graph.microsoft.com/v1.0/users"

    response = requests.get(url, headers=get_headers())
    __raise_for_status(response)
    
    users = response.json()
    return users['value']

def create_user():
    pass

def get_user(user_id: str):
    url = f"https://graph.microsoft.com/v1.0/users/{user_id}"

    response = requests.get(url, headers=get_headers())
    __raise_for_status(response)

    return response.json()


def update_user():
    pass

def delete_user(user_id: str) -> bool:
    url = f"https://graph.microsoft.com/v1.0/users/{user_id}"

    response = requests.delete(url, headers=get_headers())
    __raise_for_status(response)
    return response.status_code == 204


def get_user_id_by_email(email: str) -> str:
    filter_raw = (
        f"mail eq '{email}' or "
        f"userPrincipalName eq '{email}'"
    )

    filter_encoded = quote(filter_raw, safe="()'= ")

    url = f"https://graph.microsoft.com/v1.0/users?$filter={filter_encoded}"

    response = requests.get(url, headers=get_headers())
    __raise_for_status(response)

    items = response.json().get("value", [])

    if not items:
        raise Exception('')

    return items[0]["id"]

def delete_user_by_email(email: str):
    return delete_user(get_user_id_by_email(email))