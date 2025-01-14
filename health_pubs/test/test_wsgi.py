# import os
# import pytest
# from django.core.wsgi import get_wsgi_application


# @pytest.fixture
# def set_django_settings_env():
#     """Set the DJANGO_SETTINGS_MODULE environment variable for testing."""
#     os.environ["DJANGO_SETTINGS_MODULE"] = "health_pubs.settings"
#     yield
#     del os.environ["DJANGO_SETTINGS_MODULE"]


# def test_wsgi_application(set_django_settings_env):
#     """
#     Test the WSGI application.
#     Ensures that:
#     - The application object initializes without error.
#     - The correct Django settings module is used.
#     """
#     from health_pubs.wsgi import application

#     # Verify the WSGI application is initialized
#     assert application is not None

#     # Verify the settings module is correctly loaded
#     assert os.environ["DJANGO_SETTINGS_MODULE"] == "health_pubs.settings"

#     # Ensure the application is callable
#     assert callable(application)


# def test_wsgi_callable(set_django_settings_env):
#     """
#     Test the WSGI application initialization using Django's internal loader.
#     Ensures that the callable returned by get_wsgi_application matches the module's application.
#     """
#     from health_pubs.wsgi import application

#     # Load application using Django's get_wsgi_application
#     loaded_application = get_wsgi_application()

#     # Verify the loaded application matches the one in wsgi.py
#     assert application == loaded_application
