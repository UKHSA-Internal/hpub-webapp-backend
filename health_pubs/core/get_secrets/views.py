from rest_framework.decorators import (
    api_view,
    permission_classes,
    authentication_classes,
)
from rest_framework.response import Response

from rest_framework.permissions import AllowAny
from rest_framework.authentication import SessionAuthentication

from django.views.decorators.http import require_http_methods


import sys

import os

import pathlib


# Adjust path to configuration based on environment

target_path = pathlib.Path(os.path.abspath(__file__)).parents[2]

sys.path.append(target_path)

from configs.get_secret_config import Config

import logging

# Configure logging
logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
@api_view(["GET"])
@authentication_classes([SessionAuthentication])
@permission_classes([AllowAny])
def get_frontend_secrets(request):
    """
    Retrieve front-end specific secrets from environment variables or AWS Secrets Manager
    and return them as JSON for the frontend to ingest.
    """
    secrets_map = {
        "VITE_APP_PORT": "VITE_APP_PORT",
        "VITE_API_TARGET": "VITE_API_TARGET",
        "VITE_MSAL_CLIENT_ID": "AZURE_B2C_CLIENT_ID",
        "VITE_MSAL_AUTHORITY": "AZURE_B2C_ISSUER",
        "VITE_MSAL_REDIRECT_URI": "VITE_MSAL_REDIRECT_URI",
        "VITE_MSAL_POST_LOGOUT_REDIRECT_URI": "VITE_MSAL_POST_LOGOUT_REDIRECT_URI",
        "VITE_MSAL_KNOWN_AUTHORITIES": "AZURE_B2C_TENANT_NAME",
        "VITE_MSAL_LOGIN_REQUEST_SCOPES": "VITE_MSAL_LOGIN_REQUEST_SCOPES",
        "VITE_API_BASE_URL": "VITE_API_BASE_URL",
        "VITE_BUCKET_NAME": "VITE_BUCKET_NAME",
        "VITE_AWS_ACCESS_KEY": "VITE_AWS_ACCESS_KEY",
        "VITE_AWS_SECRET_KEY": "VITE_AWS_SECRET_KEY",
    }

    response_data = {}
    config = Config()  # Instantiate Config here to ensure it's fresh for each request
    try:
        for frontend_var, env_var_key in secrets_map.items():
            try:
                secret_value = config.get_non_secret_value(env_var_key)
                response_data[frontend_var] = secret_value
                logger.debug(
                    f"Successfully retrieved value for {frontend_var} from environment."
                )

            except EnvironmentError as e:
                logger.warning(f"Environment variable {env_var_key} not found: {e}")
                response_data[frontend_var] = None  # Or handle default value as needed

    except Exception as e:
        logger.exception(f"Error occurred while retrieving frontend secrets: {str(e)}")
        return Response(
            {"error": f"Internal server error while retrieving secrets: {str(e)}"},
            status=500,
        )

    return Response(response_data, status=200)
