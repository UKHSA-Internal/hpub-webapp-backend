import os
from unittest.mock import patch
import json
import pytest
from configs.get_secret_config import Config
from core.utils.config_loader import load_environment
from botocore.exceptions import ClientError


# Use environment variables with defaults for test credentials
TEST_USERNAME = os.getenv("TEST_USERNAME")
TEST_PASSWORD = os.getenv("TEST_PASSWORD")
TEST_DBNAME = os.getenv("TEST_DBNAME")
TEST_HOST = os.getenv("TEST_HOST")
TEST_PORT = os.getenv("TEST_PORT")

# Build the connection string using the environment-based values.
TEST_CONNECTION_STRING = (
    f"dbname={TEST_DBNAME} user={TEST_USERNAME} password={TEST_PASSWORD} "
    f"host={TEST_HOST} port={TEST_PORT}"
)


@pytest.fixture(autouse=True)
def setup_env():
    """Fixture to set up common pre-test environment."""
    load_environment()


@patch("configs.get_secret_config.get_secret_value")
@patch.dict(
    os.environ,
    {
        "AWS_API_KEY": "fake_aws_api_key",
        "GOV_UK_NOTIFY_API_KEY": "fake_notify_api_key",
        "ENVIRONMENT": "test",
    },
)
def test_get_value_from_secrets(mock_get_secret_value):
    """Test retrieving a secret value from AWS Secrets Manager."""
    mock_get_secret_value.return_value = '{"key": "secret_value"}'

    value = Config.get_value("AWS_API_KEY", is_secret=True)
    assert value == "secret_value"
    mock_get_secret_value.assert_called_once_with("fake_aws_api_key")


@patch.dict(os.environ, {"NON_SECRET_KEY": "non_secret_value"})
def test_get_non_secret_value():
    """Test retrieving a non-secret value from environment variables."""
    value = Config.get_non_secret_value("NON_SECRET_KEY")
    assert value == "non_secret_value"


@patch.dict(os.environ, {"HPUB_POSTGRES_CONNECTION_STRING": "dev/hpub/database"})
@patch("configs.get_secret_config.get_secret_value")
@patch("configs.get_secret_config.Config.parse_connection_string")
def test_db_connection_details(mock_parse_connection_string, mock_get_secret_value):
    """Test parsing of the PostgreSQL connection string using env-sourced credentials."""
    # Instead of embedding literal credentials, use the constructed connection string.
    mock_get_secret_value.return_value = json.dumps(
        {"HPUB_POSTGRES_CONNECTION_STRING": TEST_CONNECTION_STRING}
    )

    # Return a dictionary with credentials obtained from environment variables.
    mock_parse_connection_string.return_value = {
        "dbname": TEST_DBNAME,
        "user": TEST_USERNAME,
        "password": TEST_PASSWORD,
        "host": TEST_HOST,
        "port": TEST_PORT,
    }

    config = Config()
    connection_details = config.db_connection_details

    # Validate that the connection details match the values from environment variables.
    assert connection_details["dbname"] == TEST_DBNAME
    assert connection_details["user"] == TEST_USERNAME
    assert connection_details["password"] == TEST_PASSWORD
    assert connection_details["host"] == TEST_HOST
    assert connection_details["port"] == TEST_PORT

    mock_get_secret_value.assert_called_once()
    mock_parse_connection_string.assert_called_once_with(TEST_CONNECTION_STRING)


@patch("configs.get_secret_config.get_secret_value")
def test_get_secret_value_raises_client_error(mock_get_secret_value):
    """Test handling of AWS Secrets Manager errors."""
    mock_get_secret_value.side_effect = ClientError(
        {"Error": {"Code": "ResourceNotFoundException", "Message": "Secret not found"}},
        "GetSecretValue",
    )

    with pytest.raises(ClientError, match="Secret not found"):
        Config.get_value("AWS_API_KEY", is_secret=True)


@patch.dict(os.environ, {})
def test_get_value_raises_error_if_not_found():
    """Test that get_value raises an error if the key is not found."""
    with pytest.raises(
        EnvironmentError,
        match="Environment variable NON_EXISTENT_KEY is undefined or empty",
    ):
        Config.get_value("NON_EXISTENT_KEY", is_secret=False)


@patch("configs.get_secret_config.get_secret_value")
@patch.dict(
    os.environ,
    {"ENVIRONMENT": "test"},
)
def test_get_value_raises_error_for_empty_secret(mock_get_secret_value):
    """Test that an error is raised if the secret value is empty."""
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
