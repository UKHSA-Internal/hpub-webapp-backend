import json
import pytest
from unittest.mock import patch
from rest_framework.test import APIRequestFactory

from core.get_secrets.views import get_frontend_secrets


@pytest.fixture
def api_factory():
    return APIRequestFactory()


@patch("core.get_secrets.views.get_secret_value")
@patch("core.get_secrets.views.logger")
def test_get_frontend_secrets_success(mock_logger, mock_get_secret_value, api_factory):
    # Mock secret values
    mock_secrets = {
        "hpub/frontend/app/port": json.dumps({"value": "5173"}),
        "hpub/api/target": json.dumps({"value": "https://hpub.test.com"}),
    }

    def mock_get_secret(key):
        return mock_secrets.get(key, json.dumps({"value": "mock_value"}))

    mock_get_secret_value.side_effect = mock_get_secret

    request = api_factory.get("/get-frontend-secrets")
    response = get_frontend_secrets(request)

    assert response.status_code == 200
    expected_response = {
        "VITE_APP_PORT": "5173",
        "VITE_API_TARGET": "https://hpub.test.com",
        "VITE_MSAL_CLIENT_ID": "mock_value",
        "VITE_MSAL_AUTHORITY": "mock_value",
        "VITE_MSAL_REDIRECT_URI": "mock_value",
        "VITE_MSAL_POST_LOGOUT_REDIRECT_URI": "mock_value",
        "VITE_MSAL_KNOWN_AUTHORITIES": "mock_value",
        "VITE_MSAL_LOGIN_REQUEST_SCOPES": "mock_value",
        "VITE_MSAL_LOGIN_REQUEST_PROMPT": "mock_value",
        "VITE_API_BASE_URL": "mock_value",
    }
    assert response.data == expected_response


@patch("core.get_secrets.views.get_secret_value")
@patch("core.get_secrets.views.logger")
def test_get_frontend_secrets_failure(mock_logger, mock_get_secret_value, api_factory):
    # Simulate an exception when retrieving secrets
    mock_get_secret_value.side_effect = Exception("AWS Secrets Manager error")

    request = api_factory.get("/get-frontend-secrets")
    response = get_frontend_secrets(request)

    assert response.status_code == 500
    assert "error" in response.data
    assert "AWS Secrets Manager error" in response.data["error"]
    mock_logger.exception.assert_called()
