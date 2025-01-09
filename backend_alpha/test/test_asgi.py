# import os
# import pytest
# from django.core.asgi import get_asgi_application


# @pytest.fixture
# def set_django_settings_env():
#     """Set the DJANGO_SETTINGS_MODULE environment variable for testing."""
#     os.environ["DJANGO_SETTINGS_MODULE"] = "backend_alpha.settings"
#     yield
#     del os.environ["DJANGO_SETTINGS_MODULE"]


# def test_asgi_application(set_django_settings_env):
#     """
#     Test the ASGI application.
#     Ensures that:
#     - The application object initializes without error.
#     - The correct Django settings module is used.
#     """
#     from backend_alpha.asgi import application

#     # Verify the ASGI application is initialized
#     assert application is not None

#     # Verify the settings module is correctly loaded
#     assert os.environ["DJANGO_SETTINGS_MODULE"] == "backend_alpha.settings"

#     # Ensure the application is callable
#     assert callable(application)


# def test_asgi_callable(set_django_settings_env):
#     """
#     Test the ASGI application initialization using Django's internal loader.
#     Ensures that the callable returned by get_asgi_application matches the module's application.
#     """
#     from backend_alpha.asgi import application

#     # Load application using Django's get_asgi_application
#     loaded_application = get_asgi_application()

#     # Verify the loaded application matches the one in asgi.py
#     assert application == loaded_application
