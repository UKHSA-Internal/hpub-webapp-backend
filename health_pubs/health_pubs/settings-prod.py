import sys
import os
from pathlib import Path

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent

from configs.get_secret_config import Config
from corsheaders.defaults import default_headers
from urllib.parse import urlparse

# Load secrets
config = Config()
SECRET_KEY = config.get_django_secret_key()
PUBLIC_KEY = config.get_rsa_public_key()
PRIVATE_KEY = config.get_rsa_private_key()

# Database credentials
DB_NAME = config.get_db_name()
DB_USER = config.get_db_user()
DB_PASSWORD = config.get_db_password()
DB_HOST = config.get_db_host()
DB_PORT = config.get_db_port()

# Azure B2C settings
AZURE_B2C_CLIENT_ID = config.get_azure_b2c_client_id()
AZURE_B2C_SECRET_ID = config.get_azure_b2c_secret_id()
AZURE_B2C_TENANT_ID = config.get_azure_b2c_tenant_id()

# AWS S3 settings
AWS_REGION = "eu-west-2"
AWS_BUCKET_NAME = config.get_hpub_s3_bucket_name()

# Frontend URL (for CORS and CSRF)
HPUB_FRONT_END_URL = config.get_hpub_base_api_url()
parsed = urlparse(HPUB_FRONT_END_URL)
HPUB_FRONT_END_HOST_NAME = parsed.hostname
print(f"HPUB_FRONT_END_HOST_NAME: {HPUB_FRONT_END_HOST_NAME}")

# SECURITY SETTINGS
DEBUG = False
ALLOWED_HOSTS = [
    HPUB_FRONT_END_HOST_NAME,
]

# CORS CONFIGURATION
CORS_ALLOWED_ORIGINS = [
    HPUB_FRONT_END_URL,
]
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = list(default_headers) + ["x-session-id"]

# CSRF CONFIGURATION
CSRF_TRUSTED_ORIGINS = [HPUB_FRONT_END_URL]
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

# HTTPS & HSTS
SECURE_SSL_REDIRECT = True
SECURE_HSTS_SECONDS = 60000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True

# APPLICATION DEFINITION
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "corsheaders",
    "rest_framework",
    "rest_framework.authtoken",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.microsoft",
    "dj_rest_auth",
    "django_filters",
    "django_crontab",
    "django_extensions",
    "wagtail",
    "wagtail.admin",
    "wagtail.contrib.settings",
    "wagtail.api.v2",
    # Core apps
    "core.products",
    "core.roles",
    "core.orders",
    "core.establishments",
    "core.organizations",
    "core.programs",
    "core.addresses",
    "core.order_limits",
    "core.feedbacks",
    "core.event_analytics",
    "core.users",
    "core.audiences",
    "core.diseases",
    "core.vaccinations",
    "core.customer_support",
    "core.where_to_use",
    "core.languages",
    # AWS SDK (not a Django app)
    "boto3",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "health_pubs.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "health_pubs.wsgi.application"

# DATABASES
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": DB_NAME,
        "USER": DB_USER,
        "PASSWORD": DB_PASSWORD,
        "HOST": DB_HOST,
        "PORT": DB_PORT,
    }
}

# REST FRAMEWORK
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.utils.custom_token_authentication.CustomTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# CRON JOBS
CRONJOBS = [
    ("0 7 * * *", "core.products.cron.CheckDraftProductsCronJob.do"),
    ("0 0 * * *", "core.products.cron.PublishScheduledProductsCronJob.do"),
]

# INTERNATIONALIZATION
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# STATIC & MEDIA
STATIC_URL = "/static/"
STATIC_ROOT = os.path.join(BASE_DIR, "static")
MEDIA_URL = "/media/"
MEDIA_ROOT = os.path.join(BASE_DIR, "media")

# DEFAULT AUTO FIELD
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# Wagtail\ nWAGTAIL_SITE_NAME = "HPub Backend Service"
WAGTAILADMIN_BASE_URL = HPUB_FRONT_END_URL

# AUTHENTICATION BACKENDS
AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

# SITE CONFIG
SITE_ID = 1
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/user/logout/"

# ACCOUNT ADAPTERS
ACCOUNT_ADAPTER = "allauth.account.adapter.DefaultAccountAdapter"
SOCIALACCOUNT_ADAPTER = "allauth.socialaccount.adapter.DefaultSocialAccountAdapter"

# LOGGING
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s %(process)d %(thread)d %(message)s",
        },
    },
    "handlers": {
        "console": {
            "level": "INFO",
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
        }
    },
    "loggers": {
        "django": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": True,
        },
    },
}
