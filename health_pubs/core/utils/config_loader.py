import os

from dotenv import load_dotenv


def load_environment():
    """
    Load environment variables from a .env file located in the project's root directory.
    """
    # Get the directory of the current file
    current_file_dir = os.path.dirname(os.path.abspath(__file__))

    # Move two directories up from the current file's directory to reach the project root
    base_dir = os.path.abspath(os.path.join(current_file_dir, "../../"))

    # Construct the path to the .env file
    env_path = os.path.join(base_dir, "configs", ".env")

    # Load environment variables from the .env file
    load_dotenv(dotenv_path=env_path)
