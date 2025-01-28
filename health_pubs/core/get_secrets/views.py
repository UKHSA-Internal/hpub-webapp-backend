import json
from rest_framework.decorators import api_view, permission_classes, authentication_classes
from rest_framework.response import Response

from rest_framework.permissions import AllowAny
from rest_framework.authentication import SessionAuthentication
import sys
import os
import pathlib
target_path = pathlib.Path(os.path.abspath(__file__)).parents[2]
sys.path.append(target_path)
from configs.config import get_secret_value

@api_view(['GET'])
@authentication_classes([SessionAuthentication])
@permission_classes([AllowAny])
def get_frontend_secrets(request):
    """
    Retrieve front-end specific secrets from AWS Secrets Manager
    and return them as JSON for the frontend to ingest.
    """
    # Mapping of frontend variable names to the actual secrets manager keys
    secrets_map = {
        "VITE_APP_PORT": "hpub/frontend/app/port",
        "VITE_API_TARGET": "hpub/api/target",
        "VITE_MSAL_CLIENT_ID": "hpub/azure/b2c/client/id",
        "VITE_MSAL_AUTHORITY": "hpub/azure/b2c/authority",
        "VITE_MSAL_REDIRECT_URI": "hpub/azure/b2c/redirect/uri",
        "VITE_MSAL_POST_LOGOUT_REDIRECT_URI": "hpub/azure/b2c/postlogout/redirect/uri",
        "VITE_MSAL_KNOWN_AUTHORITIES": "hpub/azure/b2c/known/authorities",
        "VITE_MSAL_LOGIN_REQUEST_SCOPES": "hpub/azure/b2c/scope",
        "VITE_MSAL_LOGIN_REQUEST_PROMPT": "hpub/azure/b2c/login/request/prompt",
        "VITE_API_BASE_URL": "hpub/frontend/base/url",
    }

    # Fetch each secret from Secrets Manager
    response_data = {}
    for frontend_var, secret_key in secrets_map.items():
        response_data[frontend_var] = json.loads(get_secret_value(secret_key)).values()

    return Response(response_data)
