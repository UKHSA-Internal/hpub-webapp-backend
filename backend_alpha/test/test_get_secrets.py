import os
from unittest.mock import patch

import pytest
from configs.get_secret_config import Config
from core.utils.config_loader import load_environment


@pytest.fixture(autouse=True)
def setup_env():
    """Fixture to set up any common pre-test environment."""
    load_environment()


@patch.dict(
    os.environ,
    {
        "AWS_API_KEY": "fake_aws_api_key",
        "GOV_UK_NOTIFY_API_KEY": "fake_notify_api_key",
        "ENVIRONMENT": "test",
    },
)
@patch("configs.get_secret_config.get_secret_value")
def test_get_value_from_secrets(mock_get_secret_value):
    """Test retrieving secret value from AWS Secrets Manager."""
    mock_get_secret_value.return_value = '{"key": "secret_value"}'

    value = Config.get_value("AWS_API_KEY", is_secret=True)
    assert value == "secret_value"
    mock_get_secret_value.assert_called_once_with("fake_aws_api_key")


@patch.dict(os.environ, {"NON_SECRET_KEY": "non_secret_value"})
def test_get_non_secret_value():
    """Test retrieving non-secret value from environment."""
    value = Config.get_non_secret_value("NON_SECRET_KEY")
    assert value == "non_secret_value"


@patch.dict(os.environ, {"HPUB_POSTGRES_CONNECTION_STRING": "dev/hpub/database"})
def test_db_connection_details():
    """Test parsing of the PostgreSQL connection string."""
    config = Config()
    connection_details = config.db_connection_details

    assert connection_details["dbname"] == "devtesting"


@patch.dict(os.environ, {})
def test_get_value_raises_error_if_not_found():
    """Test that get_value raises an error if the key is not found."""
    with pytest.raises(
        EnvironmentError,
        match="Environment variable NON_EXISTENT_KEY is undefined or empty",
    ):
        Config.get_value("NON_EXISTENT_KEY", is_secret=False)


@patch.dict(
    os.environ,
    {"ENVIRONMENT": "test"},
)
@patch("configs.get_secret_config.get_secret_value")
def test_get_value_raises_error_for_empty_secret(mock_get_secret_value):
    """Test that an error is raised if the secret is empty."""
    mock_get_secret_value.return_value = ""

    with pytest.raises(ValueError, match="Secret value for AWS_API_KEY is empty."):
        Config.get_value("AWS_API_KEY", is_secret=True)


def test_parse_invalid_connection_string():
    """Test parsing an invalid PostgreSQL connection string format."""
    invalid_connection_string = "invalid_connection_string"
    with pytest.raises(
        ValueError, match="Invalid connection string format: invalid_connection_string"
    ):
        Config.parse_connection_string(invalid_connection_string)
