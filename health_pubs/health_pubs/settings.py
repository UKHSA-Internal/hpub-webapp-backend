import sys
from pathlib import Path

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

from configs.get_secret_config import Config

config = Config()
DB_NAME = config.DB_NAME
DB_HOST = config.DB_HOST
DB_USER = config.DB_USER
DB_PASSWORD = config.DB_PASSWORD
DB_PORT = config.DB_PORT
AZURE_B2C_CLIENT_ID = config.get_azure_b2c_client_id()
AZURE_B2C_SECRET_ID = config.get_azure_b2c_secret_id()
AZURE_B2C_TENANT_ID = config.get_azure_b2c_tenant_id()
DJANGO_SECRET = config.get_django_secret_key()
public_key = config.get_rsa_public_key()
private_key = config.get_rsa_private_key()

# Quick-start development settings - unsuitable for production


SECRET_KEY = DJANGO_SECRET

PUBLIC_KEY = public_key
PRIVATE_KEY = private_key


# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver", "0.0.0.0", "*"]

CORS_ALLOWED_ORIGINS = ["http://localhost:3000", "http://localhost:5173"]

CSRF_TRUSTED_ORIGINS = ["http://127.0.0.1:8085"]

CSRF_COOKIE_SECURE = False


# Application definition

INSTALLED_APPS = [
    "django.contrib.sites",
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
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "allauth.account.middleware.AccountMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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
#     'default': {
#         'BACKEND': 'django_redis.cache.RedisCache',
#         'LOCATION': get_secret_value('REDIS_URL', 'redis://localhost:6379/1'),
#         'OPTIONS': {
#             'CLIENT_CLASS': 'django_redis.client.DefaultClient',
#         }
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

WAGTAILADMIN_BASE_URL = "http://localhost:8085"


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
