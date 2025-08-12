import sys
from pathlib import Path
from datetime import timedelta

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

from configs.get_secret_config import Config

from corsheaders.defaults import default_headers


config = Config()
DB_NAME = config.get_db_name()
DB_HOST = config.get_db_host()
DB_USER = config.get_db_user()
DB_PASSWORD = config.get_db_password().strip()
DB_PORT = config.get_db_port()
AZURE_B2C_CLIENT_ID = config.get_azure_b2c_client_id()
AZURE_B2C_SECRET_ID = config.get_azure_b2c_secret_id()
AZURE_B2C_TENANT_ID = config.get_azure_b2c_tenant_id()
DJANGO_SECRET = config.get_django_secret_key()
public_key = config.get_rsa_public_key()
private_key = config.get_rsa_private_key()
HPUB_FRONT_END_URL = config.get_hpub_base_api_url()
AWS_REGION = "eu-west-2"
AWS_BUCKET_NAME = config.get_hpub_s3_bucket_name()
ACCESS_TOKEN_LIFETIME = timedelta(minutes=30)
REFRESH_TOKEN_LIFETIME = timedelta(days=1)
REFRESH_TOKEN_MAX_AGE = 86400
MAX_FEATURED_PROGRAMMES = 6
# Quick-start development settings - unsuitable for production

SECRET_KEY = DJANGO_SECRET

PUBLIC_KEY = public_key
PRIVATE_KEY = private_key


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config.get_django_debug_value()
ALLOWED_HOSTS = config.get_django_allowed_hosts()

CORS_ALLOWED_ORIGINS = config.get_cors_allowed_origins()

CORS_ALLOW_CREDENTIALS = True


CORS_ALLOW_HEADERS = list(default_headers) + [
    "x-session-id",
]


CSRF_TRUSTED_ORIGINS = config.get_csrf_trusted_origins()


SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG
SECURE_SSL_REDIRECT = not DEBUG
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_HSTS_SECONDS = 31536000 if not DEBUG else 0
SECURE_HSTS_INCLUDE_SUBDOMAINS = not DEBUG
SECURE_HSTS_PRELOAD = not DEBUG
# Trust the original host header forwarded by ALB
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")


if DEBUG:
    CACHE_TTL = 0  # effectively disables caching
else:
    CACHE_TTL = 60 * 5  # 5 minutes in prod


PRESIGNED_URL_TTL = 60 * 60  # 1 hour

# Application definition

INSTALLED_APPS = [
    "django_crontab",
    "django.contrib.sites",
    "corsheaders",
    "rest_framework.authtoken",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.microsoft",
    "dj_rest_auth",
    "django_extensions",
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.utils.http",
    "wagtail.contrib.settings",
    "wagtail.contrib",
    "wagtail",
    "wagtail.admin",
    "wagtail.snippets",
    "wagtail.search",
    "wagtail.api",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.api.v2",
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
    "rest_framework",
    "taggit",
    "core",
    "pandas",
    "segno",
    "boto3",
]


MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.utils.custom_token_authentication.CustomTokenAuthentication",
        # "rest_framework.authentication.SessionAuthentication",
    ],
    # "DEFAULT_AUTHENTICATION_CLASSES": [
    #     "core.utils.custom_token_authentication.CustomTokenAuthentication",
    # ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

CRONJOBS = [
    ("0 7 * * *", "core.products.cron.CheckDraftProductsCronJob.do"),  # 07:00 daily
    (
        "0 0 * * *",
        "core.products.cron.PublishScheduledProductsCronJob.do",
    ),  # 00:00 daily
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


# Database
# https://docs.djangoproject.com/en/5.0/ref/settings/#databases


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


#  NOTE: This will be used once I have the AWS Config for the setup
# Cache Configuration
# CACHES = {
#     "default": {
#         "BACKEND": "django_redis.cache.RedisCache",
#         "LOCATION": "redis://localhost:6379/1",
#         "OPTIONS": {
#             "CLIENT_CLASS": "django_redis.client.DefaultClient",
#         },
#     }
# }


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.CommonPasswordValidator",
    },
    {
        "NAME": "django.contrib.auth.password_validation.NumericPasswordValidator",
    },
]


# Internationalization

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True


STATIC_URL = "/static/"
STATIC_ROOT = "/app/static/"

MEDIA_URL = "/media/"
MEDIA_ROOT = "/app/media/"


# Default primary key field type
# https://docs.djangoproject.com/en/5.0/ref/settings/#default-auto-field

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

WAGTAIL_SITE_NAME = "HPub Backend Service"

if DEBUG:
    WAGTAILADMIN_BASE_URL = HPUB_FRONT_END_URL
else:
    # Assuming HPUB_FRONT_END_URL is the base URL for your production environment
    # and it should be HTTPS in production.
    WAGTAILADMIN_BASE_URL = HPUB_FRONT_END_URL.replace("http://", "https://")  # NOSONAR


AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)


SITE_ID = 1
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/user/logout/"


# Ensure that the default account adapter works well with Azure B2C
ACCOUNT_ADAPTER = "allauth.account.adapter.DefaultAccountAdapter"
SOCIALACCOUNT_ADAPTER = "allauth.socialaccount.adapter.DefaultSocialAccountAdapter"


LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "%(levelname)s %(asctime)s %(module)s "
            "%(process)d %(thread)d %(message)s",
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
