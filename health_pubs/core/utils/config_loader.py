import os
from dotenv import load_dotenv


def load_environment():
    """
    Load environment variables from the appropriate .env file based on the ENVIRONMENT variable.
    Supported environments: TEST, DEV, UAT, PROD.
    Defaults to DEV if not provided.
    """
    # Get the environment type, defaulting to DEV if not set
    env = os.environ.get("ENVIRONMENT", "DEV").upper()
    allowed_envs = {"TEST", "DEV", "UAT", "PROD"}
    if env not in allowed_envs:
        raise ValueError(
            f"Unsupported ENVIRONMENT '{env}'. Supported values are: {allowed_envs}"
        )

    # Get the directory of the current file
    current_file_dir = os.path.dirname(os.path.abspath(__file__))

    # Move two directories up from the current file's directory to reach the project root
    base_dir = os.path.abspath(os.path.join(current_file_dir, "../../"))

    # Construct the path to the environment file (e.g., .env.dev, .env.test, etc.)
    env_file_name = f".env.{env.lower()}"
    env_path = os.path.join(base_dir, "configs", env_file_name)

    # Load the environment variables from the selected file
    load_dotenv(dotenv_path=env_path)
