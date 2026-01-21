import sys
from pathlib import Path
from datetime import timedelta
import os
from urllib.parse import urlparse

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

PRODUCTS_PAGE_SIZE = 10
USERS_LIST_PAGE_SIZE = 10
ADDRESSES_LIST_PAGE_SIZE = 10
ADMIN_PRODUCTS_PAGE_SIZE = 25

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
    "idempotency-key",
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
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# ---------------- Cache TTLs ----------------
CACHE_TTL = int(os.getenv("CACHE_TTL", 60))
CACHE_TTL_DETAIL = int(os.getenv("CACHE_TTL_DETAIL", 3 if DEBUG else 60))
CACHE_TTL_LIST = int(os.getenv("CACHE_TTL_LIST", 30))
ADMIN_PRE_LIST_LIMIT = int(os.getenv("ADMIN_PRE_LIST_LIMIT", 1500))
# ---------------- Presign ----------------
PRESIGNED_URL_TTL = int(os.getenv("PRESIGNED_URL_TTL", 60 * 60 * 1))  # 1 hour
MINIMUM_PRESIGNED_URL_TTL = int(
    os.getenv("MINIMUM_PRESIGNED_URL_TTL", 60 * 30)
)  # 30 minutes
PRESIGN_IN_LISTS = os.getenv("PRESIGN_IN_LISTS", "true").lower() == "true"

# ---------------- File metadata ----------------
FILE_METADATA_ENABLED = os.getenv("FILE_METADATA_ENABLED", "true").lower() == "true"
FILE_METADATA_DEEP_PROBE_DOCS = (
    os.getenv("FILE_METADATA_DEEP_PROBE_DOCS", "true").lower() == "true"
)
MAX_METADATA_BYTES = int(os.getenv("MAX_METADATA_BYTES", 2 * 1024 * 1024))  # 2 MB
FILE_METADATA_TIME_BUDGET_MS = int(os.getenv("FILE_METADATA_TIME_BUDGET_MS", 300))
FILE_METADATA_SLOTS = [
    s.strip()
    for s in os.getenv("FILE_METADATA_SLOTS", "main_download_url").split(",")
    if s.strip()
]
FILE_METADATA_CACHE_TTL = int(os.getenv("FILE_METADATA_CACHE_TTL", 6 * 60 * 60))  # 6h

# ---------------- A/V probing ----------------
FFPROBE_TIMEOUT_SECS = int(os.getenv("FFPROBE_TIMEOUT_SECS", 3))

# ---------------- Document types ----------------
DOC_FILE_TYPES = [
    "pdf",
    "pptx",
    "txt",
    "docx",
    "doc",
    "odt",
    "ppt",
    "xlsx",
]
DOC_DEEP_PROBE_EXTS = ["pdf", "pptx", "docx", "doc", "odt", "ppt", "xlsx"]
DOCX_INCLUDE_PAGECOUNT = True
DOC_PAGECOUNT_VIA_LIBREOFFICE = True
LIBREOFFICE_BIN = "soffice"
LIBREOFFICE_TIMEOUT_SECS = 30
STRICT_DOC_PAGE_META = True

# ================= Apps =================
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
    "django_filters",
    "rest_framework",
    "taggit",
    "core",
]

# ================= Middleware =================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

# ================= REST Framework =================
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "core.utils.custom_token_authentication.CustomTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
}

# ================= Cron =================
CRONJOBS = [
    ("0 7 * * *", "core.products.cron.CheckDraftProductsCronJob.do"),
    ("0 0 * * *", "core.products.cron.PublishScheduledProductsCronJob.do"),
]

# ================= URLs & WSGI =================
ROOT_URLCONF = "health_pubs.urls"
WSGI_APPLICATION = "health_pubs.wsgi.application"

# ================= Templates =================
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

# ================= Database =================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": DB_NAME,
        "USER": DB_USER,
        "PASSWORD": DB_PASSWORD,
        "HOST": DB_HOST,
        "PORT": DB_PORT,
        **({"OPTIONS": {"sslmode": "require"}} if not DEBUG else {}),
    }
}

AWS_EXPECTED_BUCKET_OWNER = config.get_aws_expected_bucket_owner()

# ================= Cache =================
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "unique-%s-cache" % ("dev" if DEBUG else "prod"),
    }
}

# ================= Warning Suppression (Dev Only) =================
if DEBUG:
    import warnings
    from django.core.cache.backends.base import CacheKeyWarning

    warnings.filterwarnings("ignore", category=CacheKeyWarning)


#  NOTE: This will be used once I have the AWS Config for the setup
# Cache Configuration with Redis
# CACHES = {
#     "default": {
#         "BACKEND": "django_redis.cache.RedisCache",
#         "LOCATION": "redis://localhost:6379/1",
#         "OPTIONS": {
#             "CLIENT_CLASS": "django_redis.client.DefaultClient",
#         },
#     }
# }


# ================= Auth =================
AUTH_PASSWORD_VALIDATORS = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTHENTICATION_BACKENDS = (
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
)

SITE_ID = 1
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/user/logout/"
ACCOUNT_ADAPTER = "allauth.account.adapter.DefaultAccountAdapter"
SOCIALACCOUNT_ADAPTER = "allauth.socialaccount.adapter.DefaultSocialAccountAdapter"

# ================= Internationalization =================
LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

# ================= Static & Media =================
STATIC_URL = "/static/"
MEDIA_URL = "/media/"
STATIC_ROOT = "/app/static/"
MEDIA_ROOT = "/app/media/"

# ================= Wagtail =================
WAGTAIL_SITE_NAME = "Hpub Backend Service"


if not DEBUG:
    parsed = urlparse(HPUB_FRONT_END_URL)
    if parsed.scheme != "https":
        raise ValueError(
            f"Insecure HPUB_FRONT_END_URL configured: {HPUB_FRONT_END_URL}. "
            "Use HTTPS in non-DEBUG environments."
        )

WAGTAILADMIN_BASE_URL = HPUB_FRONT_END_URL

# ================= Logging =================
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
