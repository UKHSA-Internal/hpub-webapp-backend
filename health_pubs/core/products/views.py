import datetime
import json
import logging
import re
import uuid
import difflib
from typing import Any, Mapping, Optional, Union, Dict, List, Tuple
from urllib.parse import unquote
from django.utils import timezone
import time
from django.db import IntegrityError
from psycopg2 import errors as pg_errors
from collections import defaultdict
from datetime import timedelta


import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from core.audiences.models import Audience
from core.diseases.models import Disease
from core.diseases.serializers import DiseaseSerializer
from core.errors.enums import ErrorCode, ErrorMessage
from core.errors.error_function import handle_error
from core.establishments.models import Establishment
from core.languages.models import LanguagePage
from core.order_limits.models import OrderLimitPage
from core.organizations.models import Organization
from core.programs.models import Program
from core.users.models import User
from core.users.permissions import (
    IsAdminUser,
)
from core.utils.custom_token_authentication import CustomTokenAuthentication
from core.utils.extract_file_metadata import get_file_metadata
from core.utils.generate_s3_presigned_url import (
    generate_inline_presigned_urls,
    generate_presigned_urls,
)
from .filters import ProductFilter
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.conf import settings
from django.core.cache import cache
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page

from core.utils.product_recommendation_system import get_recommended_products
from core.vaccinations.models import Vaccination
from core.vaccinations.serializers import VaccinationSerializer
from core.where_to_use.models import WhereToUse
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import (
    ObjectDoesNotExist,
    ValidationError,
    ImproperlyConfigured,
)
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import generics
from .filters import ProductFilter
from rest_framework.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from django.views import View
from django.core.exceptions import ImproperlyConfigured
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.status import (
    HTTP_200_OK,
    HTTP_204_NO_CONTENT,
    HTTP_400_BAD_REQUEST,
    HTTP_403_FORBIDDEN,
    HTTP_404_NOT_FOUND,
)
from rest_framework.views import APIView
from wagtail.models import Page
from collections.abc import Mapping
from .models import Product, ProductUpdate
from .serializers import (
    ProductSearchSerializer,
    ProductSerializer,
    ProductUpdateSerializer,
    RelatedProductSerializer,
)
from wagtail.models import Page
from django.core.serializers.json import DjangoJSONEncoder

from configs.get_secret_config import Config
from django.core.exceptions import ValidationError

config = Config()

logger = logging.getLogger(__name__)

PRODUCT_CODE_PATTERN = r"^[A-Za-z0-9_-]+$"
# Constants for log messages
LOG_MSG_S3_URL_EXTRACTION = "Extracted S3 URLs for presigned URL generation: %s"
UNEXPECTED_ERROR_MSG = "An unexpected error occurred."
INTERNAL_ERROR_MSG = "An unexpected error occurred while searching for products."
PRODUCT_NOT_FOUND_LOG_MSG = "No product found with product_code: %s"

# Global constant for valid sort fields
VALID_SORT_FIELDS = [
    "product_title",
    "-product_title",
    "created_at",
    "-created_at",
    "updated_at",
    "-updated_at",
    "publish_date",
    "-publish_date",
    "version_number",
    "-version_number",
]


_DIGITS = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_BASE = len(_DIGITS)
# default TTLs (in seconds)
CACHE_TTL = getattr(settings, "CACHE_TTL")


CANONICAL_TAGS = {"download-only", "download-or-order", "order-only"}


def normalize_tag(raw: str) -> str:
    if not raw:
        return ""
    cleaned = raw.strip().lower().replace("_", "-")
    # fix extremely common misspellings manually if needed
    if cleaned == "donwload-only":
        cleaned = "download-only"
    # fuzzy-match to canonical tags (optional, helpful for other typos)
    if cleaned not in CANONICAL_TAGS:
        close = difflib.get_close_matches(cleaned, CANONICAL_TAGS, n=1, cutoff=0.8)
        if close:
            cleaned = close[0]
    return cleaned


def generate_product_key(last_key: str | None) -> str:
    """
    Increments a base-36 “number” whose digits run 0–9 then A–Z.
    If last_key is None, returns '1'. Otherwise rolls over so that:

      '0' → '1'
      '9' → 'A'
      'Z' → '10'
      '10' → '11'
      etc.
    """
    # very first key
    if not last_key:
        return "1"

    # turn into list of integer positions (0..35)
    try:
        positions = [_DIGITS.index(ch) for ch in last_key]
    except ValueError as e:
        raise ValueError(f"Invalid last_key: {last_key!r}") from e

    # add one, carrying through
    i, carry = len(positions) - 1, 1
    while i >= 0 and carry:
        positions[i] += 1
        if positions[i] >= _BASE:
            positions[i] = 0
            carry = 1
        else:
            carry = 0
        i -= 1

    # if we still have a carry, prepend '1' (i.e. index 1 in _DIGITS)
    if carry:
        positions.insert(0, _DIGITS.index("1"))

    # rebuild the string
    return "".join(_DIGITS[pos] for pos in positions)


def get_next_product_key(program_name: str) -> str:
    """
    Looks up all existing keys for this program, finds the
    max in our custom ordering, and returns the next one.
    """
    # pull all keys into Python so we can do a proper numeric max
    keys = list(
        Product.objects.filter(program_name=program_name).values_list(
            "product_key", flat=True
        )
    )

    last = max(keys, key=lambda k: _key_to_int(k)) if keys else None
    next_key = generate_product_key(last)
    logging.info("get_next_product_key: %r → %r", last, next_key)
    return next_key


def _key_to_int(key: str) -> int:
    """
    Converts a key like '1', '9', 'A', 'Z', '11', '1Z', etc.
    into a plain integer so we can compare them properly.
    """
    value = 0
    for ch in key:
        idx = _DIGITS.index(ch)
        value = value * _BASE + idx
    return value


def get_next_version_number(program_id, product_key, iso_language_code):
    """
    Retrieves the next available version number for a given program_id, product_key, and iso_language_code.

    Args:
        program_id (int): The ID of the program.
        product_key (str): The product_key.
        iso_language_code (str): The language code.

    Returns:
        int: The next available version number.
    """
    last_product = (
        Product.objects.filter(
            program_id=program_id,
            product_key=product_key,
            iso_language_code=iso_language_code,
        )
        .order_by("-version_number")
        .first()
    )

    if last_product:
        return last_product.version_number + 1
    else:
        return 1  # Start with version 001


def _extract_urls_from_downloads(product_downloads):
    """Helper to extract s3_bucket_url values from a product_downloads dict."""
    urls = []
    main_download = product_downloads.get("main_download_url")
    if isinstance(main_download, dict):
        s3_url = main_download.get("s3_bucket_url")
        if s3_url:
            urls.append(s3_url)

    # Use a list comprehension to extract s3_bucket_url values from other download types.
    urls.extend(
        item.get("s3_bucket_url")
        for key in ("web_download_url", "print_download_url", "transcript_url")
        for item in product_downloads.get(key, [])
        if isinstance(item, dict) and item.get("s3_bucket_url")
    )
    return urls


def _update_downloads_with_presigned(product_downloads, presigned_urls):
    """Helper to update product_downloads dict with presigned URLs.

    Returns True if any update was performed.
    """
    # If product_downloads is a JSON string, convert it to a dictionary.
    if isinstance(product_downloads, str):
        try:
            product_downloads = json.loads(product_downloads)
        except json.JSONDecodeError as e:
            # Log the error or handle it accordingly.
            logger.info(f"Failed to parse product_downloads JSON: {e}")
            return False

    updated = False
    for key in [
        "main_download_url",
        "web_download_url",
        "print_download_url",
        "transcript_url",
    ]:
        items = product_downloads.get(key)
        if items:
            updated |= _update_items_with_presigned(items, presigned_urls)
    return updated


def _update_items_with_presigned(items, presigned_urls):
    """Helper to update individual items with presigned URLs."""
    updated = False
    if isinstance(items, dict):
        updated |= _update_dict_item(items, presigned_urls)
    elif isinstance(items, list):
        for item in items:
            updated |= _update_dict_item(item, presigned_urls)
    return updated


def _update_dict_item(item, presigned_urls):
    """Update a single dictionary item with a presigned URL if applicable."""
    updated = False
    s3_url = item.get("s3_bucket_url")
    if s3_url and (presigned_url := presigned_urls.get(s3_url)):
        item["URL"] = presigned_url
        updated = True
    return updated


def extract_s3_urls(products_data):
    """Extract S3 URLs from products data for presigned URL generation."""
    all_download_urls = []
    for product in products_data:
        update_refs = product.get("update_ref")
        if isinstance(update_refs, dict):
            product_downloads = update_refs.get("product_downloads", {})
            all_download_urls.extend(_extract_urls_from_downloads(product_downloads))
        else:
            logger.warning(
                "Expected update_ref to be a dictionary but got %s",
                type(update_refs).__name__,
            )
    return all_download_urls


def update_product_urls(products_data, presigned_urls):
    """Update product URLs with presigned URLs in the serialized data."""
    for product in products_data:
        update_refs = product.get("update_ref")
        if isinstance(update_refs, dict):
            product_downloads = update_refs.get("product_downloads", {})
            _update_downloads_with_presigned(product_downloads, presigned_urls)
        else:
            logger.warning(
                "Expected update_ref to be a dictionary but got %s",
                type(update_refs).__name__,
            )


def _update_product_downloads_with_presigned_urls(product_data, presigned_urls):
    """Update product download URLs with presigned URLs."""
    for product in product_data:
        logger.info("Updating Product: %s", product.product_id)

        # Fetch the product instance
        product_instance = Product.objects.filter(product_id=product.product_id).first()
        if product_instance and product_instance.update_ref:
            update_refs = product_instance.update_ref
            product_downloads = update_refs.product_downloads
            if _update_downloads_with_presigned(product_downloads, presigned_urls):
                update_refs.save()
        else:
            logger.warning(
                "No product_instance or update_ref found for product_id: %s",
                product.product_id,
            )


def _prepare_response_data(products, serialized_data, product_code, product_title):
    matched_titles = list(products.values_list("product_title", flat=True))
    matched_codes = list(products.values_list("product_code", flat=True))
    return {
        "matched_product_titles": matched_titles if product_title else None,
        "matched_product_codes": matched_codes if product_code else None,
        "product_info": serialized_data,
    }


def get_product(product_code: str) -> Optional[Product]:
    """Fetch the latest version of the product by its product code.
    Returns None if the product is not found.
    """
    product = (
        Product.objects.filter(product_code__startswith=product_code)
        .order_by("-version_number")
        .first()
    )

    if not product:
        return handle_error(
            ErrorCode.PRODUCT_NOT_FOUND,
            ErrorMessage.PRODUCT_NOT_FOUND,
            status.HTTP_404_NOT_FOUND,
        )

    return product


def handle_exceptions(exception):
    """Handle different types of exceptions."""
    if isinstance(exception, DatabaseError):
        logger.exception("Database error occurred while retrieving products.")
        return handle_error(
            ErrorCode.DATABASE_ERROR,
            ErrorMessage.DATABASE_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    elif isinstance(exception, TimeoutError):
        logger.exception("Timeout error occurred while retrieving products.")
        return handle_error(
            ErrorCode.TIMEOUT_ERROR,
            ErrorMessage.TIMEOUT_ERROR,
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    else:
        logger.exception("An unexpected error occurred while retrieving products.")
        return handle_error(
            ErrorCode.INTERNAL_SERVER_ERROR,
            ErrorMessage.INTERNAL_SERVER_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


def _handle_invalid_query_param():
    return handle_error(
        ErrorCode.INVALID_QUERY_PARAM,
        ErrorMessage.INVALID_QUERY_PARAM,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


def _handle_database_error():
    logger.exception("A database error occurred while searching for products.")
    return handle_error(
        ErrorCode.DATABASE_ERROR,
        ErrorMessage.DATABASE_ERROR,
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _handle_timeout_error():
    logger.exception("A timeout error occurred while searching for products.")
    return handle_error(
        ErrorCode.TIMEOUT_ERROR,
        ErrorMessage.TIMEOUT_ERROR,
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
    )


def filter_live_languages(products_data):
    """
    Given a list of serialized product dictionaries, filter the 'existing_languages'
    field so that only languages with a live product (determined by the product code
    extracted from the language's product_url) are retained.
    """
    # Gather all language product codes from every product.
    product_codes = {
        lang["product_url"].split("/")[-1]
        for product in products_data
        for lang in product.get("existing_languages", [])
    }
    # Bulk query: find all product codes that are live.
    live_codes = set(
        Product.objects.filter(product_code__in=product_codes, status="live")
        .values_list("product_code", flat=True)
        .distinct()
    )
    # Update each product's 'existing_languages' to keep only those with live codes.
    for product in products_data:
        product["existing_languages"] = [
            lang
            for lang in product.get("existing_languages", [])
            if lang["product_url"].split("/")[-1] in live_codes
        ]
    return products_data


class CustomPagination(PageNumberPagination):
    page_size = 10  # Set pagination to 10 items per page

    def get_paginated_response(self, data, status_code=200):
        response = Response(
            {
                "links": {
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
                "count": self.page.paginator.count,
                "results": data,
            }
        )
        response.status_code = status_code

        return response


class ErrorHandlingMixin:
    """
    Mixin to wrap view dispatch with common error handling.
    Any exception raised in the view method will be caught here.
    """

    # Mapping exception types to their handling parameters:
    # (log message format, error code, error message, status code, logger function)
    EXCEPTION_HANDLERS = {
        DatabaseError: (
            "Database error: %s",
            ErrorCode.DATABASE_ERROR,
            ErrorMessage.DATABASE_ERROR,
            500,
            logger.exception,
        ),
        TimeoutError: (
            "Timeout error: %s",
            ErrorCode.TIMEOUT_ERROR,
            ErrorMessage.TIMEOUT_ERROR,
            504,
            logger.exception,
        ),
        ValidationError: (
            "Validation error: %s",
            ErrorCode.INVALID_DATA,
            ErrorMessage.INVALID_DATA,
            400,
            logger.exception,
        ),
        AttributeError: (
            "Attribute error: %s",
            ErrorCode.ATTRIBUTE_ERROR,
            ErrorMessage.ATTRIBUTE_ERROR,
            400,
            logger.error,
        ),
    }

    def dispatch(self, request, *args, **kwargs):
        try:
            return super().dispatch(request, *args, **kwargs)
        except Exception as e:
            # Loop through our mapping to see if the caught exception matches
            for exc_type, (
                log_fmt,
                err_code,
                err_msg,
                status,
                log_func,
            ) in self.EXCEPTION_HANDLERS.items():
                if isinstance(e, exc_type):
                    log_func(log_fmt, str(e))
                    return handle_error(err_code, err_msg, status_code=status)
            # Fallback for unexpected exceptions
            logger.exception("Unexpected error: %s", str(e))
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=500,
            )


class ProductUtilsMixin:
    # ---- Constants ----
    DATE_INPUT_FORMATS = ("%Y-%m-%d", "%m/%d/%Y")
    DATETIME_INPUT_FORMATS = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
    )
    DATE_SENTINELS = {"immediately", "no_end_date", "specific_date"}
    INVALID_STRINGS = {"-", "nan", "n/a", "na"}
    NUMERIC_COLS = {
        "unit_of_measure",
        "programme_id",
        "language_id",
        "audience_ids",
        "where_to_use_ids",
        "vaccinations_ids",
        "disease_ids",
        "minimum_stock_level",
        "order_limit_value",
    }
    DEFAULT_ORDER_LIMITS = {
        "Private": 5,
        "Private company": 5,
        "Private health": 5,
        "Education": 100,
        "Government": 100,
        "Local government": 500,
        "Social care": 500,
        "Stakeholder": 100,
        "Voluntary services": 100,
        "NHS": 500,
    }

    # ---- Core cleaning entrypoint ----

    @classmethod
    def clean_row_data(cls, raw_row: Mapping[str, Any]) -> Dict[str, Any]:
        """Orchestrate all field‐level cleaning/coercion."""
        row = {k: cls.none_if_na(v) for k, v in raw_row.items()}
        row = cls._remove_invalid_strings(row)
        cls._parse_booleans(row)
        cls._normalize_product_type(row)
        cls._trim_alternative_type(row)
        cls._map_choices(row)
        cls._clean_numerics(row)
        cls._clean_codes(row)
        cls._coerce_dates(row)
        cls._propagate_email_fields(row)
        logger.debug("Cleaned row data: %r", row)
        return row

    # ---- Basic null & string cleaning ----

    @staticmethod
    def none_if_na(value: Any) -> Any:
        if value is None:
            return None
        if isinstance(
            value, (pd._libs.missing.NAType, pd._libs.tslibs.nattype.NaTType)
        ):
            return None
        if pd.isna(value):
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @classmethod
    def _remove_invalid_strings(cls, row: Dict[str, Any]) -> Dict[str, Any]:
        for k, v in row.items():
            if isinstance(v, str) and v.strip().lower() in cls.INVALID_STRINGS:
                row[k] = None
        return row

    @staticmethod
    def _parse_booleans(row: Dict[str, Any]) -> None:
        val = str(row.get("run_to_zero") or "").strip().lower()
        row["run_to_zero"] = val in {"y", "yes", "true", "1"}

    # ---- Choice normalization ----

    @classmethod
    def _normalize_product_type(cls, row: Dict[str, Any]) -> None:
        raw = row.get("product_type")
        choices: List[str]
        try:
            choices = [
                val for val, _ in ProductUpdate._meta.get_field("product_type").choices
            ]
        except Exception:
            choices = []
        row["product_type"] = cls._choose_best(raw, choices)

    @staticmethod
    def _choose_best(raw: Any, choices: List[str]) -> Optional[str]:
        if not isinstance(raw, str) or not raw.strip():
            return None
        s = raw.strip()
        for c in choices:
            if s.lower() == c.lower():
                return c
        # singular/plural fallback
        base = s.rstrip("s")
        for c in choices:
            if base.lower() == c.lower() or (base + "s").lower() == c.lower():
                return c
        return None

    @staticmethod
    def _trim_alternative_type(row: Dict[str, Any]) -> None:
        alt = row.get("alternative_type")
        if isinstance(alt, str):
            row["alternative_type"] = alt.strip() or None

    @staticmethod
    def _map_choices(row: Dict[str, Any]) -> None:
        def map_choice(raw: Any, mapping: Dict[str, str]) -> Optional[str]:
            if isinstance(raw, str):
                return mapping.get(raw.strip().lower())
            return None

        row["available_from_choice"] = map_choice(
            row.get("available_from_choice") or row.get("available_from_date"),
            {"immediately": "immediately", "specific_date": "specific_date"},
        )
        row["available_until_choice"] = map_choice(
            row.get("available_until_choice") or row.get("available_until_date"),
            {"no_end_date": "no_end_date", "specific_date": "specific_date"},
        )

    # ---- Numeric cleaning ----

    @classmethod
    def _clean_numerics(cls, row: Dict[str, Any]) -> None:
        for col in cls.NUMERIC_COLS:
            row[col] = cls._clean_numeric_field(row.get(col))

    @staticmethod
    def _clean_numeric_field(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            if isinstance(value, str):
                v = value.strip()
                if "," in v:
                    parts = [str(int(float(x))) for x in v.split(",") if x.strip()]
                    return ",".join(parts) if parts else None
                if v.replace(".", "", 1).isdigit():
                    return str(int(float(v)))
            elif isinstance(value, (int, float)) and not pd.isna(value):
                return str(int(value))
        except Exception:
            logger.exception("Error normalising numeric field %r", value)
        return None

    # ---- Code cleaning ----

    @classmethod
    def _clean_codes(cls, row: Dict[str, Any]) -> None:
        row["local_code"] = cls._clean_local_code(row.get("local_code"))
        row["cost_centre"] = cls._clean_alphanumeric_code(row.get("cost_centre"))

    @staticmethod
    def _clean_alphanumeric_code(value: Any) -> Optional[str]:
        if value is None:
            return None
        v = str(value).strip()
        if not v:
            return None
        if v.isdigit():
            return f"{int(v):03d}"
        return v.upper()

    @staticmethod
    def _clean_local_code(value: Any) -> Optional[str]:
        if value is None:
            return None
        try:
            num = float(value)
            if num.is_integer():
                return f"{int(num):04d}"
        except Exception:
            pass
        v = str(value).strip()
        if not v:
            return None
        if v.lower() == "i":
            return "0001"
        return v.upper()

    # ---- Date/time coercion ----

    @classmethod
    def _coerce_dates(cls, row: Dict[str, Any]) -> None:
        row["created"] = cls._coerce_datetime(row.get("created"))
        row["version_date"] = cls._coerce_date(row.get("version_date"))
        for dc in ("order_from_date", "order_until_date", "order_end_date"):
            row[dc] = cls._coerce_date(row.get(dc))

    @classmethod
    def _coerce_date(cls, value: Any) -> Optional[datetime.date]:
        v = cls.none_if_na(value)
        if v is None:
            return None
        if isinstance(v, (pd.Timestamp, datetime.datetime)):
            return v.date()
        if isinstance(v, datetime.date):
            return v
        if isinstance(v, str) and v.strip().lower() not in cls.DATE_SENTINELS:
            for fmt in cls.DATE_INPUT_FORMATS:
                try:
                    return datetime.datetime.strptime(v, fmt).date()
                except ValueError:
                    continue
        logger.warning("Could not parse date %r — defaulting to today()", v)
        return datetime.date.today()

    @classmethod
    def _coerce_datetime(cls, value: Any) -> datetime.datetime:
        v = cls.none_if_na(value)
        if isinstance(v, pd.Timestamp):
            dt = v.to_pydatetime()
        elif isinstance(v, datetime.datetime):
            dt = v
        elif isinstance(v, str):
            for fmt in cls.DATETIME_INPUT_FORMATS:
                try:
                    dt = datetime.datetime.strptime(v, fmt)
                    break
                except ValueError:
                    continue
            else:
                logger.warning("Unsupported datetime %r — using now()", v)
                dt = timezone.now()
        else:
            dt = timezone.now()

        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_default_timezone())
        return dt

    # ---- Misc propagation ----

    @staticmethod
    def _propagate_email_fields(row: Dict[str, Any]) -> None:
        if row.get("stock_owner"):
            row["stock_owner_email_address"] = row["stock_owner"]
        if row.get("stock_referral"):
            row["order_referral_email_address"] = row["stock_referral"]

    # ---- Safe tree insertion ----

    def safe_add_child(self, parent: Page, instance: Page) -> Page:
        try:
            return parent.add_child(instance=instance)
        except AttributeError as exc:
            if "_inc_path" in str(exc):
                size = getattr(Page, "_path_step", 4)
                seg = str(1).zfill(size)
                instance.depth = parent.depth + 1
                instance.path = parent.path + seg
                instance.save()
                return instance
            raise

    # ---- Order limits creation ----

    def create_order_limits(self, product: Product, row: Dict[str, Any]) -> List[str]:
        supplied = self._parse_order_limits(row)
        created_names: List[str] = []
        # apply explicit first, then defaults
        for name, limit in {**self.DEFAULT_ORDER_LIMITS, **supplied}.items():
            if self._make_single_limit(product, name, limit):
                created_names.append(name)
        return created_names

    @staticmethod
    def _parse_order_limits(row: Dict[str, Any]) -> Dict[str, int]:
        out: Dict[str, int] = {}
        raw_names = row.get("organization_names")
        raw_val = row.get("order_limit_value")
        if raw_names and raw_val not in (None, ""):
            try:
                lim = int(str(raw_val).strip())
                for nm in map(str.strip, str(raw_names).split(",")):
                    if nm:
                        out[nm] = lim
            except ValueError:
                logger.warning("Invalid order_limit_value %r", raw_val)
        return out

    def _make_single_limit(self, product: Product, name: str, limit: int) -> bool:
        org = Organization.objects.filter(name=name).first()
        if not org:
            logger.warning("Organization %r not found — skipping", name)
            return False
        ol = OrderLimitPage(
            title=f"Order limit for {name}",
            slug=f"ol-{org.id}-{uuid.uuid4().hex[:6]}",
            order_limit_id=str(uuid.uuid4()),
            order_limit=limit,
            product_ref=product,
            organization_ref=org,
        )
        res = self.safe_add_child(product, ol)
        return not (isinstance(res, dict) and res.get("skip"))

    # ---- M2M assignment ----

    def assign_m2m_fields(
        self,
        instance,
        m2m_map: Dict[str, Tuple[str, Any, str, str]],
        row: Mapping[str, Any],
        *,
        add_only: bool = False,
    ) -> Dict[str, List[str]]:
        names: Dict[str, List[str]] = {}
        for col, (attr_name, model, lookup, resp_key) in m2m_map.items():
            raw = row.get(col)
            mgr = getattr(instance, attr_name)
            if not raw:
                if not add_only:
                    mgr.clear()
                names[resp_key] = []
                continue

            ids = [s.strip() for s in str(raw).split(",") if s.strip()]
            objs = list(model.objects.filter(**{f"{lookup}__in": ids}))

            if add_only:
                existing = {str(x) for x in mgr.values_list(lookup, flat=True)}
                mgr.add(*[o for o in objs if str(getattr(o, lookup)) not in existing])
            else:
                mgr.set(objs)

            names[resp_key] = [
                getattr(o, "name", str(getattr(o, lookup))) for o in objs
            ]

        instance.save()
        return names

    # ---- Product & Update creation ----

    def create_product_update(self, row: Mapping[str, Any]) -> ProductUpdate:
        return ProductUpdate(
            title=str(row.get("title") or "Unnamed update"),
            slug=f"update-{uuid.uuid4().hex[:8]}",
            minimum_stock_level=row.get("minimum_stock_level"),
            quantity_available=row.get("quantity_available", 0),
            run_to_zero=row.get("run_to_zero", False),
            available_from_choice=row.get("available_from_choice"),
            order_from_date=row.get("order_from_date"),
            available_until_choice=row.get("available_until_choice"),
            order_end_date=row.get("available_until_choice") == "specific_date"
            and row.get("order_until_date")
            or row.get("order_end_date"),
            product_type=row.get("product_type"),
            alternative_type=row.get("alternative_type"),
            cost_centre=row.get("cost_centre"),
            local_code=row.get("local_code"),
            unit_of_measure=row.get("unit_of_measure"),
            summary_of_guidance=row.get("guidance"),
            stock_owner_email_address=row.get("stock_owner_email_address"),
            order_referral_email_address=row.get("order_referral_email_address"),
            product_downloads={
                "main_download_url": row.get("main_download_file_name", {}),
                "web_download_url": row.get("web_download_file_name", {}),
                "print_download_url": row.get("print_download_file_name", {}),
                "transcript_download_url": row.get("print_download_file_name", {}),
                "video_url": row.get("video_urls", ""),
            },
        )

    def create_product(
        self,
        row: Mapping[str, Any],
        program: Optional[Program],
        language: Optional[LanguagePage],
        iso_code: str,
        pu: ProductUpdate,
        created_at: datetime.datetime,
        publish_date: datetime.date,
    ) -> Product:
        user = None
        if row.get("user_id"):
            user = User.objects.filter(user_id=str(row["user_id"])).first()

        base = str(row.get("title") or "")
        return Product(
            title=base,
            slug=f"{slugify(base)}-{uuid.uuid4().hex[:6]}",
            user_ref=user,
            product_id=str(uuid.uuid4()),
            program_name=(program.programme_name if program else ""),
            product_title=base,
            status=row.get("status"),
            product_code=str(row.get("product_code") or "").strip(),
            file_url=row.get("gov_related_article"),
            tag=str(row.get("tag") or "").strip().lower(),
            product_key=row.get("product_key"),
            program_id=program,
            language_id=language,
            version_number="001",
            iso_language_code=iso_code.upper(),
            language_name=row.get("language_name"),
            update_ref=pu,
            created_at=created_at,
            is_latest=True,
            publish_date=publish_date,
            suppress_event=False,
        )

    # ---- Row processing helpers ----

    def _prepare_flags(self, row: Dict[str, Any]) -> Tuple[bool, bool]:
        tag = normalize_tag(str(row.get("tag") or ""))
        row["tag"] = tag
        return tag == "live", tag == "download-only"

    def _update_existing(
        self,
        code: str,
        row: Dict[str, Any],
        is_live: bool,
        is_download_only: bool,
        m2m_map,
    ) -> Optional[Dict[str, Any]]:
        prod = Product.objects.filter(product_code=code).first()
        if not prod:
            return None

        for field, key in {
            "file_url": "gov_related_article",
            "summary_of_guidance": "guidance",
        }.items():
            inc = row.get(key)
            if inc and not getattr(prod, field):
                setattr(prod, field, inc)
        prod.save()

        if prod.update_ref:
            self.assign_m2m_fields(prod.update_ref, m2m_map, row, add_only=True)
        order_count = 0
        if is_live and not is_download_only:
            order_count = len(self.create_order_limits(prod, row))

        return {
            "created": False,
            "updated": True,
            "order_limits": order_count,
            "warnings": [],
            "errors": [],
        }

    def _create_new(
        self,
        idx: int,
        row: Dict[str, Any],
        root: Page,
        is_live: bool,
        is_download_only: bool,
        m2m_map,
    ) -> Dict[str, Any]:
        warnings: List[str] = []
        errors: List[str] = []

        # Required‐fields validation
        required: set = set()
        if is_live:
            if is_download_only:
                required = {
                    "product_key",
                    "title",
                    "language_id",
                    "gov_related_article",
                    "product_code",
                    "programme_id",
                    "status",
                    "created",
                    "language_name",
                    "product_type",
                    "guidance",
                    "alternative_type",
                    "tag",
                    "user_id",
                    "vaccinations_ids",
                    "disease_ids",
                    "audience_ids",
                    "where_to_use_ids",
                }
            else:
                required = {
                    "product_key",
                    "title",
                    "language_id",
                    "gov_related_article",
                    "product_code",
                    "programme_id",
                    "status",
                    "created",
                    "unit_of_measure",
                    "minimum_stock_level",
                    "available_from_choice",
                    "available_until_choice",
                    "order_from_date",
                    "product_type",
                    "audience_ids",
                    "where_to_use_ids",
                    "stock_owner_email_address",
                    "order_referral_email_address",
                    "run_to_zero",
                    "alternative_type",
                    "local_code",
                    "cost_centre",
                    "tag",
                    "user_id",
                    "language_name",
                    "guidance",
                    "vaccinations_ids",
                    "disease_ids",
                    "order_limit_value",
                    "organization_names",
                }
                if row.get("available_until_choice") == "specific_date":
                    required.add("order_until_date")

        def _missing(field: str) -> bool:
            val = row.get(field)
            return val is None or (isinstance(val, str) and not val.strip())

        missing = [f for f in required if _missing(f)]
        if missing:
            msg = f"Row {idx+1} missing: {', '.join(sorted(missing))}"
            logger.warning(msg)
            warnings.append(msg)

        # Timestamps
        created_dt = self._coerce_datetime(row.get("created"))
        pub_date = self._coerce_date(row.get("version_date")) or datetime.date.today()

        # Program & Language lookups
        program = None
        pid = row.get("programme_id")
        if pid:
            program = Program.objects.filter(program_id=str(pid)).first()
            if is_live and not program:
                w = f"Program {pid} not found"
                logger.warning(w)
                warnings.append(w)

        language = None
        iso_code = ""
        lid = row.get("language_id")
        if lid:
            language = LanguagePage.objects.filter(language_id=lid).first()
            if is_live and not language:
                w = f"Language {lid} not found"
                logger.warning(w)
                warnings.append(w)
            iso_code = language.iso_language_code if language else ""

        # Create ProductUpdate
        pu_obj = self.create_product_update(row)
        res_pu = self.safe_add_child(root, pu_obj)
        if isinstance(res_pu, dict) and res_pu.get("skip"):
            err = "Failed to attach ProductUpdate"
            logger.error(err)
            errors.append(err)
            return {
                "created": False,
                "updated": False,
                "order_limits": 0,
                "warnings": warnings,
                "errors": errors,
            }
        pu = res_pu
        self.assign_m2m_fields(pu, m2m_map, row, add_only=False)

        # Create Product
        prod_obj = self.create_product(
            row, program, language, iso_code, pu, created_dt, pub_date
        )
        try:
            prod_obj.full_clean()
        except ValidationError as ve:
            w = f"Validation issues: {ve}"
            logger.warning(w)
            warnings.append(w)

        res_prod = self.safe_add_child(pu, prod_obj)
        if isinstance(res_prod, dict) and res_prod.get("skip"):
            err = "Failed to attach Product"
            logger.error(err)
            errors.append(err)
            return {
                "created": False,
                "updated": False,
                "order_limits": 0,
                "warnings": warnings,
                "errors": errors,
            }

        # Order limits
        ol_count = 0
        if is_live and not is_download_only:
            ol_count = len(self.create_order_limits(res_prod, row))

        return {
            "created": True,
            "updated": False,
            "order_limits": ol_count,
            "warnings": warnings,
            "errors": errors,
        }

    def _process_row(
        self,
        idx: int,
        row: Mapping[str, Any],
        root: Page,
        m2m_map: Dict[str, Tuple[str, Any, str, str]],
    ) -> Dict[str, Any]:
        """Master row‐by‐row import logic, delegates to helpers."""
        try:
            is_live, is_download_only = self._prepare_flags(row)
            code = str(row.get("product_code") or "").strip()
            if code:
                existing_res = self._update_existing(
                    code, row, is_live, is_download_only, m2m_map
                )
                if existing_res:
                    existing_res["skip"] = False
                    return existing_res
            new_res = self._create_new(
                idx, row, root, is_live, is_download_only, m2m_map
            )
            new_res["skip"] = False
            return new_res
        except Exception as exc:
            logger.exception("Row %d unexpected error", idx + 1)
            return {
                "skip": False,
                "created": False,
                "updated": False,
                "order_limits": 0,
                "warnings": [],
                "errors": [str(exc)],
            }


class ProductViewSet(ProductUtilsMixin, viewsets.ViewSet):
    authentication_classes: List = []
    permission_classes: List = []

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request):
        df, error_resp = self._load_dataframe(request)
        if error_resp:
            return error_resp

        try:
            root = self.get_or_create_root_page()
        except Exception as exc:
            logger.exception("Unable to get/create products root")
            return Response(
                {
                    "error": "Cannot find or create products root page.",
                    "details": str(exc),
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        m2m_map = {
            "audience_ids": ("audience_ref", Audience, "audience_id", "audience_names"),
            "where_to_use_ids": (
                "where_to_use_ref",
                WhereToUse,
                "where_to_use_id",
                "where_to_use_names",
            ),
            "vaccinations_ids": (
                "vaccination_ref",
                Vaccination,
                "vaccination_id",
                "vaccination_names",
            ),
            "disease_ids": ("diseases_ref", Disease, "disease_id", "disease_names"),
        }

        summary = []
        created_count = updated_count = order_limits_count = 0

        for idx, row_series in df.iterrows():
            raw = row_series.to_dict()
            cleaned = self.clean_row_data(raw)
            try:
                with transaction.atomic():
                    result = self._process_row(idx, cleaned, root, m2m_map)
            except Exception as exc:
                logger.exception("Row %d catastrophic error", idx + 1)
                result = {
                    "skip": False,
                    "created": False,
                    "updated": False,
                    "order_limits": 0,
                    "warnings": [],
                    "errors": [str(exc)],
                }

            if result.get("updated"):
                updated_count += 1
            elif result.get("created"):
                created_count += 1
            order_limits_count += result.get("order_limits", 0)

            summary.append(
                {
                    "row": idx + 1,
                    "created": result.get("created", False),
                    "updated": result.get("updated", False),
                    "order_limits": result.get("order_limits", 0),
                    "warnings": result.get("warnings", []),
                    "errors": result.get("errors", []),
                }
            )

        return Response(
            {
                "message": "Bulk upload complete.",
                "created_products": created_count,
                "updated_products": updated_count,
                "order_limits_created": order_limits_count,
                "row_summary": summary,
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _load_dataframe(request):
        file = request.FILES.get("product_excel")
        if not file:
            return None, Response(
                {"error": "No Excel file uploaded (field 'product_excel')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            file.seek(0)
            df = pd.read_excel(file, engine="openpyxl", keep_default_na=True)
            df = df.replace({pd.NA: None, pd.NaT: None}).where(pd.notna(df), None)
        except Exception as exc:
            logger.exception("Error parsing spreadsheet")
            return None, Response(
                {"error": "Could not parse spreadsheet.", "details": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if df.empty:
            return None, Response(
                {"error": "Uploaded spreadsheet has no data rows."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return df, None

    @action(
        detail=False,
        methods=["get"],
        url_path="related-products/(?P<product_code>[\w-]+)",
    )
    def related_publications(self, request, product_code=None):
        """
        Return related publications grouped by product_type, up to 2 each,
        with a has_more flag.
        """
        try:
            product = Product.objects.get(product_code=product_code)
        except Product.DoesNotExist:
            return Response({"error": "Product not found."}, status=404)

        pu = product.update_ref
        if not pu:
            return Response(
                {"error": "No associated product update found."}, status=404
            )

        disease_ids = list(pu.diseases_ref.values_list("disease_id", flat=True))
        disease_ids = list(map(str, disease_ids))
        candidates = (
            Product.objects.select_related("update_ref")
            .filter(update_ref__diseases_ref__in=disease_ids)
            .exclude(product_code=product_code)
            .distinct()
        )
        if not candidates.exists():
            return Response({})

        # Build similarity matrix
        rows = []
        for p in candidates:
            rows.append(
                {
                    "product_code": p.product_code,
                    "product_title": p.product_title,
                    "summary_of_guidance": p.update_ref.summary_of_guidance or "",
                    "product_type": p.update_ref.product_type or "",
                }
            )
        df = pd.DataFrame(rows)
        df["text"] = (
            df["product_title"]
            + " "
            + df["summary_of_guidance"]
            + " "
            + df["product_type"]
        )
        ref_text = (
            product.product_title
            + " "
            + (pu.summary_of_guidance or "")
            + " "
            + (pu.product_type or "")
        )
        texts = [ref_text] + df["text"].tolist()

        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf = vectorizer.fit_transform(texts)
        sims = cosine_similarity(tfidf[0:1], tfidf[1:]).flatten()
        df["score"] = sims
        df = df[df["score"] > 0.18]

        grouped: Dict[str, Dict[str, Any]] = {}
        ITEMS_PER_TYPE = 2
        for ptype, grp in df.groupby("product_type"):
            sorted_grp = grp.sort_values("score", ascending=False)
            codes = sorted_grp["product_code"].tolist()
            top = codes[:ITEMS_PER_TYPE]
            has_more = len(codes) > ITEMS_PER_TYPE
            objs = Product.objects.filter(product_code__in=top)
            serializer = RelatedProductSerializer(objs, many=True)
            grouped[ptype] = {
                "items": serializer.data,
                "has_more": has_more,
                "total_count": len(codes),
            }

        return Response(grouped)

    def get_or_create_root_page(self) -> Page:
        try:
            return Page.objects.get(slug="products-root")
        except Page.DoesNotExist:
            site_root = Page.get_first_root_node()
            if not site_root:
                raise ImproperlyConfigured("No root Page in Wagtail.")
            root = ProductUpdate(title="Products Root", slug="products-root")
            site_root.add_child(instance=root)
            return root


class PresignedUrlMixin:
    """Handles presigned URL extraction and injection, including metadata."""

    def _process_presigned_urls(self, response_data):
        update_refs = response_data.get("update_ref")
        if not isinstance(update_refs, dict):
            return

        product_downloads = update_refs.get("product_downloads")
        if not isinstance(product_downloads, dict):
            return

        # 1. Collect all S3 URLs
        all_download_urls = self._collect_s3_urls(product_downloads)
        logger.info(LOG_MSG_S3_URL_EXTRACTION, all_download_urls)

        # 2. Generate presigned URLs and inline presigned URLs
        presigned_urls = generate_presigned_urls(all_download_urls)
        inline_presigned_urls = generate_inline_presigned_urls(all_download_urls)

        # 3. Retrieve metadata for the presigned URLs
        metadata_list = get_file_metadata(list(presigned_urls.values()))
        metadata_dict = {meta["URL"]: meta for meta in metadata_list}

        # 4. Process the main download
        if "main_download_url" in product_downloads:
            product_downloads["main_download_url"] = self._apply_metadata_and_presigned(
                product_downloads.get("main_download_url"),
                presigned_urls,
                inline_presigned_urls,
                metadata_dict,
            )

        # 5. Process other download types
        for download_type in [
            "web_download_url",
            "print_download_url",
            "transcript_url",
        ]:
            downloads = product_downloads.get(download_type, [])
            if isinstance(downloads, list):
                product_downloads[download_type] = [
                    self._apply_metadata_and_presigned(
                        item, presigned_urls, inline_presigned_urls, metadata_dict
                    )
                    for item in downloads
                ]

    def _collect_s3_urls(self, product_downloads):
        urls = []

        # Handle main_download_url as either a dict or a list of dicts
        main = product_downloads.get("main_download_url")
        if isinstance(main, dict):
            urls.append(main.get("s3_bucket_url"))
        elif isinstance(main, list):
            for item in main:
                if isinstance(item, dict) and item.get("s3_bucket_url"):
                    urls.append(item["s3_bucket_url"])

        # The rest stays the same…
        for download_type in [
            "web_download_url",
            "print_download_url",
            "transcript_url",
        ]:
            downloads = product_downloads.get(download_type, [])
            if isinstance(downloads, list):
                urls.extend(
                    item.get("s3_bucket_url")
                    for item in downloads
                    if isinstance(item, dict) and item.get("s3_bucket_url")
                )
        return urls

    def _apply_metadata_and_presigned(
        self, item, presigned_urls, inline_presigned_urls, metadata_dict
    ):
        """
        Update a single download entry, but also handle lists for main_download_url
        """
        # If it's a list, process each element
        if isinstance(item, list):
            return [
                self._apply_metadata_and_presigned(
                    i, presigned_urls, inline_presigned_urls, metadata_dict
                )
                for i in item
            ]

        # … existing dict handling below
        if not isinstance(item, dict):
            return item

        s3_url = item.get("s3_bucket_url", "")
        if s3_url in presigned_urls:
            presigned_url = presigned_urls[s3_url]
            item["URL"] = presigned_url
            if presigned_url in metadata_dict:
                item.update(metadata_dict[presigned_url])
            item["s3_bucket_url"] = s3_url

        if s3_url in inline_presigned_urls:
            item["inline_presigned_s3_url"] = inline_presigned_urls[s3_url]

        return item


@method_decorator(cache_page(CACHE_TTL), name="dispatch")
class ProductDetailView(ErrorHandlingMixin, PresignedUrlMixin, viewsets.ViewSet):
    """
    GET /api/products/{product_code}/ → JSON with presigned URLs & metadata,
    automatically cached per-URL+user for CACHE_TTL seconds.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [AllowAny]

    def retrieve(self, request, product_code=None, *args, **kwargs):
        # product_code may be URL-encoded
        code = unquote(product_code or "")
        cache_key = f"product_detail:{request.user.id if request.user.is_authenticated else 'anon'}:{code}"
        cached = cache.get(cache_key)
        if cached:
            return JsonResponse(cached, status=status.HTTP_200_OK)

        logger.info("Retrieving product details for %s", code)
        product = Product.objects.filter(product_code=code).first()
        if not product:
            logger.warning("Product not found: %s", code)
            return handle_error(
                ErrorCode.PRODUCT_NOT_FOUND,
                ErrorMessage.PRODUCT_NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        data = ProductSerializer(product, context={"request": request}).data
        self._process_presigned_urls(data)
        cache.set(cache_key, data, CACHE_TTL)

        logger.info("Returning details for product %s", code)
        return JsonResponse(data, status=status.HTTP_200_OK)


class ProductDetailDelete(ErrorHandlingMixin, View):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def delete(self, request, product_code, *args, **kwargs):
        decoded_product_code = unquote(product_code)
        logger.info(
            "Attempting to delete product with product_code: %s", decoded_product_code
        )

        product = Product.objects.filter(
            product_code__startswith=decoded_product_code
        ).first()
        if not product:
            logger.warning(PRODUCT_NOT_FOUND_LOG_MSG, decoded_product_code)
            return handle_error(
                ErrorCode.PRODUCT_NOT_FOUND,
                ErrorMessage.PRODUCT_NOT_FOUND,
                status_code=HTTP_404_NOT_FOUND,
            )

        if product.status not in ["draft", "live", "archived"]:
            logger.warning(
                "Cannot withdraw product %s as it is not in draft, live, or archived status.",
                decoded_product_code,
            )
            return handle_error(
                ErrorCode.INVALID_DATA,
                ErrorMessage.INVALID_DATA,
                status_code=HTTP_403_FORBIDDEN,
            )

        # Change product status to 'withdrawn' instead of deleting it.
        product.status = "withdrawn"
        product.save()
        return JsonResponse(
            {"message": "Product archived successfully."}, status=HTTP_204_NO_CONTENT
        )


class ProductDeleteAll(View):
    def delete(self, request, *args, **kwargs):
        logger.info("Attempting to delete all products.")

        try:
            # Delete all products from the database
            deleted_count1 = Product.objects.all().delete()
            deleted_count2 = ProductUpdate.objects.all().delete()
            logger.info(f"Deleted {deleted_count1} products successfully.")
            logger.info(f"Deleted {deleted_count2} product update successfully.")

            return JsonResponse(
                {"message": f"Deleted {deleted_count1} products successfully."},
                status=204,
            )

        except DatabaseError:
            logger.exception("Database error occurred while deleting all products.")
            return JsonResponse(
                {"error": "Database error occurred while deleting all products."},
                status=500,
            )
        except Exception:
            logger.exception(
                "An unexpected error occurred while deleting all products."
            )
            return JsonResponse(
                {"error": UNEXPECTED_ERROR_MSG},
                status=500,
            )


class ProductStatusUpdateView(View):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    """
    View to handle updating the status of a product via PUT requests.
    """

    ALLOWED_TRANSITIONS = {
        "draft": ["live", "withdrawn"],
        "live": ["archived", "withdrawn", "draft"],
        "archived": ["withdrawn"],
    }

    def put(self, request, product_code, *args, **kwargs) -> JsonResponse:
        decoded_product_code = unquote(product_code)
        logger.info(
            f"Attempting to update status for product with product_code: {decoded_product_code}"
        )

        # Validate product_code pattern
        if product_code and not re.match(PRODUCT_CODE_PATTERN, product_code):
            logger.warning(f"Invalid product_code format: {product_code}")
            return _handle_invalid_query_param()

        try:
            product = self.get_product(decoded_product_code)
            if not product:
                logger.warning(f"Product with code {decoded_product_code} not found.")
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=HTTP_404_NOT_FOUND,
                )

            # Validate and obtain the new status using a helper method.
            validation = self._validate_status_update(product, request)
            if isinstance(validation, JsonResponse):
                return validation
            new_status = validation

            # if we’re moving from live → draft, set suppress_event so no signals fire
            if product.status == "live" and new_status == "draft":
                product.suppress_event = True
                logger.info(
                    f"Moving product {product.product_code} live→draft; suppress_event set to True"
                )
            product.status = new_status

            # If transitioning to "live" and publish_date is not already set, update it to today's date.
            if new_status == "live" and not product.publish_date:
                product.publish_date = timezone.now().date()
            try:
                product.save()
                logger.info(
                    f"Product status updated to {new_status} for product_code: {decoded_product_code}"
                )
            except DatabaseError as e:
                logger.error(
                    f"Database error while updating product {decoded_product_code}: {str(e)}"
                )
                return handle_error(
                    ErrorCode.DATABASE_ERROR,
                    ErrorMessage.DATABASE_ERROR,
                    status_code=500,
                )

            return JsonResponse(
                {"message": "Product status updated successfully."}, status=HTTP_200_OK
            )

        except (DatabaseError, TimeoutError) as e:
            logger.exception(f"Error occurred while updating product status: {str(e)}")
            return handle_error(
                (
                    ErrorCode.DATABASE_ERROR
                    if isinstance(e, DatabaseError)
                    else ErrorCode.TIMEOUT_ERROR
                ),
                (
                    ErrorMessage.DATABASE_ERROR
                    if isinstance(e, DatabaseError)
                    else ErrorMessage.TIMEOUT_ERROR
                ),
                status_code=500 if isinstance(e, DatabaseError) else 504,
            )
        except json.JSONDecodeError:
            logger.warning("Invalid JSON data provided for updating product status.")
            return handle_error(
                ErrorCode.INVALID_DATA,
                ErrorMessage.INVALID_DATA,
                status_code=HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception(f"An unexpected error occurred: {str(e)}")
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=500,
            )

    def get_product(self, decoded_product_code: str):
        """
        Retrieve a product instance based on the product code.
        Note: Updated to query on the correct field 'product_code'.
        """
        try:
            return Product.objects.get(product_code=decoded_product_code)
        except Product.DoesNotExist:
            return None

    def get_status_from_request(self, request) -> Optional[str]:
        """Extract the new status from the request body with logging."""
        try:
            raw_data = request.body.decode("utf-8")
            logger.info(f"Received request body: {raw_data}")
            data = json.loads(raw_data)
            return data.get("status")
        except json.JSONDecodeError as e:
            logger.error(f"JSON decode error: {str(e)}")
            return None

    def is_valid_status(self, status: str) -> bool:
        """Check if the provided status is valid."""
        valid_statuses = self.get_valid_statuses()
        return status in valid_statuses

    def get_valid_statuses(self):
        """Helper function to retrieve valid statuses for a product."""
        return [choice[0] for choice in Product._meta.get_field("status").choices or []]

    def is_invalid_status_transition(
        self, current_status: str, new_status: str
    ) -> bool:
        """
        Check if the status transition is invalid based on the allowed transitions.
        """
        allowed_next_statuses = self.ALLOWED_TRANSITIONS.get(current_status, [])
        return new_status not in allowed_next_statuses

    def check_required_fields(self, product: Product) -> list:
        """
        Check for missing required fields in the Product and ProductUpdateSerializer.

        Args:
            product (Product): The product instance to check.

        Returns:
            list: A list of missing required fields.
        """
        missing_fields = []

        # Check required fields in Product
        for field in ["product_title", "language_id", "program_id", "update_ref"]:
            if not getattr(product, field):
                missing_fields.append(field)

        serializer = (
            ProductUpdateSerializer(product.update_ref, context={"tag": product.tag})
            if product.update_ref
            else ProductUpdateSerializer(context={"tag": product.tag})
        )
        for field, field_value in serializer.data.items():
            if field_value in [None, "", [], {}] and serializer.fields[field].required:
                missing_fields.append(field)

        return missing_fields

    def _validate_status_update(
        self, product: Product, request
    ) -> Union[str, JsonResponse]:
        """
        Validates the status update request. It ensures that:
        - A new status is provided in the request.
        - The new status is one of the valid statuses.
        - The status transition from the current product status to the new status is allowed.
        - For a transition to "live", all required fields are present.
        - No other product with the same product_code is already in the target status.

        Returns:
            new_status (str): If the update is valid.
            JsonResponse: In case of any validation error.
        """
        new_status = self.get_status_from_request(request)
        if not new_status:
            logger.warning("Missing or invalid status in request body.")
            return handle_error(
                ErrorCode.INVALID_DATA,
                "Missing status in request.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        if not self.is_valid_status(new_status):
            logger.warning(f"Invalid status provided: {new_status}")
            return handle_error(
                ErrorCode.INVALID_STATUS,
                f"Invalid status provided: {new_status}",
                status_code=HTTP_400_BAD_REQUEST,
            )

        if self.is_invalid_status_transition(product.status, new_status):
            logger.warning(
                f"Invalid status transition from {product.status} to {new_status}."
            )
            return handle_error(
                ErrorCode.INVALID_STATUS_TRANSITION,
                f"Cannot transition from {product.status} to {new_status}.",
                status_code=HTTP_400_BAD_REQUEST,
            )

        # Extra Check: Ensure no duplicate product with the same product_code and new_status exists.
        if product.status != new_status:
            duplicate = Product.objects.filter(
                product_code=product.product_code, status=new_status
            ).exclude(pk=product.pk)
            if duplicate.exists():
                logger.warning(
                    f"Cannot update product {product.product_code} to {new_status}: another product with the same product_code already has this status."
                )
                return handle_error(
                    ErrorCode.DUPLICATE_STATUS,  # Ensure this error code is defined in your project.
                    f"Product with product_code {product.product_code} already exists in status {new_status}.",
                    status_code=HTTP_400_BAD_REQUEST,
                )

        # Additional check: if transitioning to "live", ensure that all required fields are set.
        if new_status == "live":
            missing_fields = self.check_required_fields(product)
            if missing_fields:
                logger.warning(
                    f"Cannot update product to live. Missing required fields: {missing_fields}"
                )
                return handle_error(
                    ErrorCode.MISSING_REQUIRED_FIELDS,
                    f"Missing required fields: {', '.join(missing_fields)}",
                    status_code=HTTP_400_BAD_REQUEST,
                )

        return new_status


class ProductUpdateView(View):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    """
    This is a view to handle updating a product's details.

    Methods:
        put: Handles PUT requests to update product information based on the provided product_code.
    """

    def put(self, request, product_code: str, *args, **kwargs) -> JsonResponse:
        """
        Update a product with the given product_code.

        Args:
            request (HttpRequest): The HTTP request object containing the updated product data.
            product_code (str): The product code used to identify the product to be updated.

        Returns:
            JsonResponse: A JSON response containing the result of the update operation.
        """

        decoded_product_code = unquote(product_code)
        logger.info(f"Updating product with product_code: {decoded_product_code}")

        try:
            # Fetch the most recent product version by the provided product_code
            product = (
                Product.objects.filter(product_code__startswith=decoded_product_code)
                .order_by("-version_number")
                .first()
            )

            if not product:
                logger.warning(
                    f"No product found with product_code: {decoded_product_code}"
                )
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status.HTTP_404_NOT_FOUND,
                )

            # Parse and validate the request data
            data = json.loads(request.body)
            serializer = ProductSerializer(
                product, data=data, partial=True, context={"request": request}
            )
            if serializer.is_valid():
                serializer.save()
                logger.info(
                    f"Product updated successfully for product_code: {decoded_product_code}"
                )
                return JsonResponse(serializer.data, status=status.HTTP_200_OK)
            else:
                logger.error(
                    f"Serializer errors during product update: {serializer.errors}"
                )
                return handle_error(
                    ErrorCode.INVALID_DATA,
                    ErrorMessage.INVALID_DATA,
                    status.HTTP_400_BAD_REQUEST,
                )

        except DatabaseError:
            logger.exception("Database error occurred while updating product.")
            return handle_error(
                ErrorCode.DATABASE_ERROR,
                ErrorMessage.DATABASE_ERROR,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except TimeoutError:
            logger.exception("Timeout error occurred while updating product.")
            return handle_error(
                ErrorCode.TIMEOUT_ERROR,
                ErrorMessage.TIMEOUT_ERROR,
                status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except json.JSONDecodeError:
            logger.warning("Invalid JSON data provided for product update.")
            return handle_error(
                ErrorCode.INVALID_DATA,
                ErrorMessage.INVALID_DATA,
                status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            logger.exception("An unexpected error occurred while updating the product.")
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProductPatchView(ErrorHandlingMixin, APIView):
    """
    Optimized view to handle product updates via PATCH requests.
    Pre-creates the ProductUpdate so that post_save signals see a valid update_ref.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def patch(self, request, product_code, *args, **kwargs) -> JsonResponse:
        decoded_product_code = unquote(product_code)
        logger.info("Updating product with product_code: %s", decoded_product_code)

        product = get_product(decoded_product_code)
        if not product:
            logger.warning(PRODUCT_NOT_FOUND_LOG_MSG, decoded_product_code)
            return handle_error(
                ErrorCode.PRODUCT_NOT_FOUND,
                ErrorMessage.PRODUCT_NOT_FOUND,
                status.HTTP_404_NOT_FOUND,
            )

        data = json.loads(request.body)
        logger.info("Received data for update: %s", data)
        product_type = data.get("product_type")
        product_downloads = data.get("product_downloads", {})

        # Prepare file URLs
        file_urls = self.process_file_urls(
            product_type, data, product_downloads, product.tag
        )

        # Validate date fields
        available_from_choice = data.get("available_from_choice")
        order_from_date = data.get("order_from_date")
        if available_from_choice == "specific_date" and not order_from_date:
            logger.error("order_from_date must be provided for 'specific_date'.")
        available_until_choice = data.get("available_until_choice")
        order_end_date = data.get("order_end_date")
        if available_until_choice == "specific_date" and not order_end_date:
            logger.error("order_end_date must be provided for 'specific_date'.")
            return handle_error(
                ErrorCode.MISSING_ORDER_FROM_DATE,
                ErrorMessage.MISSING_ORDER_FROM_DATE,
                status_code=400,
            )

        # Build the ProductUpdate payload
        product_update_data = self.prepare_product_update_data(
            data,
            available_until_choice,
            available_from_choice,
            order_from_date,
            order_end_date,
            file_urls,
        )

        with transaction.atomic():
            # Update or create order limits
            if data.get("order_limits"):
                self.update_order_limits(product, data.get("order_limits"))

            # Pre-create or update ProductUpdate so signals see required fields
            product_update = self.get_or_create_product_update(
                product, product_update_data
            )
            # Apply any foreign-key guidance sets immediately on the update_ref
            self.update_foreign_keys(product_update, data)

            # Now patch the Product itself
            serializer = ProductSerializer(
                product, data=data, partial=True, context={"request": request}
            )
            if serializer.is_valid():
                serializer.save()

                # Prepare response
                response_data = serializer.data
                response_data["update_ref"] = ProductUpdateSerializer(
                    product_update, context={"request": request}
                ).data

                logger.info(
                    "Product updated successfully for product_code: %s",
                    decoded_product_code,
                )
                return JsonResponse(response_data, status=status.HTTP_200_OK)

            else:
                logger.error("Serializer errors: %s", serializer.errors)
                return handle_error(
                    ErrorCode.INVALID_DATA, ErrorMessage.INVALID_DATA, status_code=400
                )

    def process_file_urls(
        self, product_type: str, data: dict, product_downloads: dict, product_tag: str
    ) -> dict:
        """
        Process file URLs by validating required downloads (if provided), initializing URLs,
        validating file extensions, and adding metadata (including presigned URLs).
        """
        if not product_downloads:
            return {}

        if isinstance(product_downloads, str):
            try:
                product_downloads = json.loads(product_downloads)
            except json.JSONDecodeError:
                raise ValidationError("Invalid JSON format for product_downloads")

        # Validate based on the input payload—not the product table.
        self.validate_required_downloads(
            product_type, data, product_downloads, product_tag
        )

        file_urls = self.initialize_file_urls(product_downloads)
        file_urls = self.validate_file_extensions(file_urls)
        return self.add_file_metadata(file_urls)

    def validate_required_downloads(
        self, product_type: str, data: dict, product_downloads: dict, product_tag: str
    ):
        """
        Validates that all required downloads are present.
        For order-only products, the input product_downloads must include only 'main_download'.
        For download-only products, the 'print_download' requirement will be ignored while validating.
        For other product types, the standard required downloads are enforced.
        """
        tag = product_tag.lower()
        logger.info(
            "Validating required downloads for product_type: %s, tag: %s",
            product_type,
            tag,
        )  # for debugging

        # For order-only, require only the main_download.
        if tag == "order-only":
            if not product_downloads.get("main_download"):
                raise ValidationError(
                    "Missing required main_download for order-only product."
                )
            return

        # Define the standard required downloads for each product type.
        required = {
            "Audio": ["main_download", "web_download", "transcript"],
            "Bulletins": ["main_download", "print_download", "web_download"],
            "Immunisation Schedule": ["main_download", "web_download"],
            "Factsheets": ["main_download", "print_download", "web_download"],
            "Briefing sheet": ["main_download", "web_download"],
            "Flyer": ["main_download", "print_download", "web_download"],
            "Guidance": ["main_download", "print_download", "web_download"],
            "Memoire": ["main_download", "print_download", "web_download"],
            "Alternative": ["main_download", "print_download", "web_download"],
            "Consent Form": ["main_download", "print_download", "web_download"],
            "Images": ["main_download", "web_download"],
            "Leaflets": ["main_download", "print_download", "web_download"],
            "Postcards": ["main_download", "print_download", "web_download"],
            "Posters": ["main_download", "print_download", "web_download"],
            "Pull-Up Banners": ["main_download", "print_download", "web_download"],
            "Stickers": ["main_download", "print_download", "web_download"],
            "Record Cards": ["main_download", "print_download", "web_download"],
            "Z-Card": ["main_download", "print_download", "web_download"],
            "Fridge Magnet": ["main_download", "print_download", "web_download"],
            "Video": ["main_download", "web_download", "video_url"],
            "GIF": ["main_download", "web_download"],
            "Slides": ["main_download", "web_download"],
        }
        # Check if the product type is in the required downloads.
        if product_type in required:
            # Make a copy to modify the required keys.
            required_downloads = required[product_type].copy()
            # For download-only products, remove 'print_download' from the required keys.
            if tag == "download-only" and "print_download" in required_downloads:
                required_downloads.remove("print_download")
            missing = [d for d in required_downloads if d not in product_downloads]
            if missing:
                raise ValidationError(
                    f"Missing required downloads for {product_type}: {', '.join(missing)}."
                )

    def initialize_file_urls(self, product_downloads: dict) -> dict:
        """
        Pull out just the raw URL strings (so later code can safely do .split('.'))
        whether the user passed ["https://…", …] or [{"URL": "https://…", …}, …].
        """

        def extract_str(key):
            raw = product_downloads.get(key, "")
            if isinstance(raw, dict):
                return raw.get("URL", "")
            return raw or ""

        def extract_list(key):
            raw = product_downloads.get(key, [])
            if not isinstance(raw, list):
                return []
            normalized = []
            for item in raw:
                if isinstance(item, dict):
                    url = item.get("URL")
                    if url:
                        normalized.append(url)
                elif isinstance(item, str):
                    normalized.append(item)
            return normalized

        return {
            "main_download_url": extract_str("main_download"),
            "web_download_url": extract_list("web_download"),
            "print_download_url": extract_list("print_download"),
            "transcript_url": extract_list("transcript"),
            "video_url": extract_str("video_url"),
        }

    def validate_file_extensions(self, file_urls: dict) -> dict:
        allowed = {
            "main_download_url": ["jpg", "jpeg", "png", "gif"],
            "transcript_url": ["pdf", "txt", "srt"],
            "web_download_url": [
                "jpg",
                "jpeg",
                "png",
                "mp4",
                "mov",
                "avi",
                "pdf",
                "pptx",
                "gif",
                "mp3",
                "wav",
                "txt",
                "docx",
                "doc",
                "odt",
                "ppt",
                "xlsx",
            ],
            "print_download_url": [
                "pdf",
                "gif",
                "png",
                "jpg",
                "jpeg",
                "docx",
                "doc",
                "odt",
                "ppt",
                "xlsx",
            ],
        }

        # single string
        main = file_urls["main_download_url"]
        if main:
            ext = main.rsplit(".", 1)[-1].lower()
            if ext not in allowed["main_download_url"]:
                file_urls["main_download_url"] = ""

        # lists
        for key in ["web_download_url", "print_download_url", "transcript_url"]:
            filtered = []
            for url in file_urls[key]:
                ext = url.rsplit(".", 1)[-1].lower()
                if ext in allowed[key]:
                    filtered.append(url)
            file_urls[key] = filtered

        return file_urls

    def add_file_metadata(self, file_urls: dict) -> dict:
        all_urls = []
        if file_urls.get("main_download_url"):
            all_urls.append(file_urls["main_download_url"])
        for key, value in file_urls.items():
            if key != "main_download_url" and isinstance(value, list):
                all_urls.extend(value)

        presigned = generate_presigned_urls(all_urls)
        inline_presigned = generate_inline_presigned_urls(all_urls)
        metadata_list = get_file_metadata(list(presigned.values()))
        metadata_dict = {meta["URL"]: meta for meta in metadata_list}

        for key, value in file_urls.items():
            if key == "main_download_url" and value:
                presigned_url = presigned.get(value)
                meta = metadata_dict.get(presigned_url, {"URL": value})
                meta["s3_bucket_url"] = value
                meta["inline_presigned_s3_url"] = inline_presigned.get(value, "")
                file_urls[key] = meta
            elif isinstance(value, list):
                file_urls[key] = [
                    {
                        **metadata_dict.get(presigned.get(url), {"URL": url}),
                        "s3_bucket_url": url,
                        "inline_presigned_s3_url": inline_presigned.get(url, ""),
                    }
                    for url in value
                ]
        return file_urls

    def prepare_product_update_data(
        self,
        data: dict,
        available_until_choice: str,
        available_from_choice: str,
        order_from_date: str,
        order_end_date: str,
        file_urls: dict,
    ) -> dict:
        allowed_fields = [
            "minimum_stock_level",
            "maximum_order_quantity",
            "order_exceptions",
            "product_type",
            "alternative_type",
            "run_to_zero",
            "cost_centre",
            "local_code",
            "unit_of_measure",
            "summary_of_guidance",
            "order_referral_email_address",
            "stock_owner_email_address",
        ]
        update_data = {
            field: data.get(field) for field in allowed_fields if field in data
        }
        if "available_from_choice" in data:
            update_data["available_from_choice"] = available_from_choice
            if available_from_choice == "specific_date":
                update_data["order_from_date"] = order_from_date
        if "available_until_choice" in data:
            update_data["available_until_choice"] = available_until_choice
            if available_until_choice == "specific_date":
                update_data["order_end_date"] = order_end_date
        if "product_downloads" in data:
            update_data["product_downloads"] = json.dumps(
                file_urls, cls=DjangoJSONEncoder
            )
        update_data["title"] = "Product_Update Title"
        update_data["slug"] = slugify("product-update" + str(datetime.datetime.now()))
        if update_data.get("run_to_zero") is True:
            update_data["minimum_stock_level"] = 0
        return update_data

    def _is_path_collision(self, exc):
        cause = getattr(exc, "__cause__", None)
        return (
            isinstance(cause, pg_errors.UniqueViolation)
            and getattr(cause.diag, "constraint_name", "")
            == "wagtailcore_page_path_key"
        )

    def get_or_create_product_update(
        self, product: Product, update_data: dict
    ) -> ProductUpdate:
        """
        Attempts up to 3 times to lock the parent, then create or update the ProductUpdate.
        Retries on path-key collisions.
        """
        for attempt in range(3):
            try:
                with transaction.atomic():
                    parent_page = product.get_parent()
                    # lock the parent so no two processes allocate the same child path
                    Page.objects.select_for_update().get(pk=parent_page.pk)

                    if product.update_ref:
                        # existing → just update fields
                        product_update = product.update_ref
                        for key, val in update_data.items():
                            setattr(product_update, key, val)
                        product_update.save()
                    else:
                        # new → create under locked parent
                        product_update = ProductUpdate(**update_data)
                        parent_page.add_child(instance=product_update)
                        product_update.save_revision().publish()
                        # link it back onto the product
                        Product.objects.filter(pk=product.pk).update(
                            update_ref=product_update
                        )
                        product.refresh_from_db()
                        product_update = product.update_ref

                    return product_update

            except IntegrityError as exc:
                if self._is_path_collision(exc) and attempt < 2:
                    # exponential backoff
                    time.sleep(0.1 * (2**attempt))
                    continue
                # non-collision or maxed-out → bubble up
                raise

        # fallback: if someone else created it meantime, fetch it
        existing = Product.objects.get(pk=product.pk).update_ref
        if existing:
            return existing

        raise RuntimeError("Could not create or find ProductUpdate after retries")

    def update_order_limits(self, product: Product, order_limits: list):
        """
        Upserts OrderLimitPage records instead of wholesale delete & recreate.
        Keeps existing pages when unchanged, updates when modified, creates when new,
        and deletes only those no longer needed.

        Result: far fewer Wagtail unpublish/delete/publish cycles → much faster.
        """
        try:
            parent_page = Page.objects.get(slug="products")
        except Page.DoesNotExist:
            logger.error("Parent page with slug 'products' not found.")
            return

        # --- Existing pages grouped by org name ----------------------------------
        existing_pages = (
            OrderLimitPage.objects.child_of(parent_page)
            .filter(product_ref=product)
            .select_related("organization_ref")
        )
        by_org = {p.organization_ref.name: p for p in existing_pages}

        # --- Prefetch org + establishment data -----------------------------------
        org_names = [
            lim["organization_name"]
            for lim in order_limits
            if lim.get("organization_name")
        ]
        org_qs = Organization.objects.filter(name__in=org_names)
        org_cache = {org.name: org for org in org_qs}

        est_qs = Establishment.objects.filter(organization_ref__in=org_qs).values(
            "organization_ref_id", "full_external_key"
        )
        full_keys_map = defaultdict(list)
        for est in est_qs:
            full_keys_map[est["organization_ref_id"]].append(est["full_external_key"])

        # --- Upsert loop ----------------------------------------------------------
        seen_orgs = set()

        for lim in order_limits:
            org_name = lim.get("organization_name")
            if not org_name:
                continue

            org = org_cache.get(org_name)
            if not org:
                logger.warning("Organization '%s' not found. Skipping.", org_name)
                continue

            limit_val = lim.get("order_limit_value", 0)
            full_keys = full_keys_map.get(org.organization_id, [])
            seen_orgs.add(org_name)

            # ------------------------------------------------------------------
            # Case A: existing page → update if changed
            # ------------------------------------------------------------------
            if org_name in by_org:
                page = by_org[org_name]
                if (
                    page.order_limit != limit_val
                    or page.full_external_keys != full_keys
                ):
                    page.order_limit = limit_val
                    page.full_external_keys = full_keys
                    page.save_revision().publish()
                continue

            # ------------------------------------------------------------------
            # Case B: new page → create
            # ------------------------------------------------------------------
            logger.info("full_external_keys for %s: %s", org_name, full_keys)
            new_page = OrderLimitPage(
                title=f"Order Limit for {org_name}",
                slug=slugify(f"{org_name}-order-limit-{uuid.uuid4()}"),
                order_limit=limit_val,
                product_ref=product,
                organization_ref=org,
                full_external_keys=full_keys,
            )
            parent_page.add_child(instance=new_page)
            new_page.save_revision().publish()

        # --- Delete pages for orgs no longer supplied ----------------------------
        for org_name, page in by_org.items():
            if org_name not in seen_orgs:
                page.delete()

    def update_foreign_keys(self, product_update: ProductUpdate, data: dict):
        mapping = [
            ("audience_names", Audience, "audience_ref"),
            ("vaccination_names", Vaccination, "vaccination_ref"),
            ("disease_names", Disease, "diseases_ref"),
            ("where_to_use_names", WhereToUse, "where_to_use_ref"),
        ]
        for field_name, model_class, relationship_field in mapping:
            if field_name in data:
                names = data.get(field_name)
                if not names:
                    continue
                refs = list(model_class.objects.filter(name__in=names))
                getattr(product_update, relationship_field).set(refs)
        product_update.save()


class ProductCreateView(ErrorHandlingMixin, APIView):
    """
    Optimized view to handle product creation via POST requests.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, *args, **kwargs):
        logger.info("ProductCreateView POST method called")
        data = json.loads(request.body)
        logger.info("Data received: %s", data)

        required_fields = [
            "product_title",
            "language_id",
            "file_url",
            "program_name",
            "tag",
            "user_id",
        ]
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            logger.warning("Missing required fields: %s", missing_fields)
            return handle_error(
                ErrorCode.MISSING_FIELD, ErrorMessage.MISSING_FIELD, status_code=400
            )

        product_title = data["product_title"]
        language_id = data["language_id"]
        file_url = data["file_url"]
        program_name = data["program_name"]
        product_id = data.get("product_id")
        tag = data.get("tag")
        publish_date = data.get("publish_date") or None

        if not LanguagePage.objects.filter(language_id=language_id).exists():
            logger.warning("Language ID %s does not exist.", language_id)
            return handle_error(
                ErrorCode.INVALID_DATA,
                ErrorMessage.LANGUAGE_ID_DOES_NOT_EXIST,
                status_code=400,
            )

        if not Program.objects.filter(programme_name=program_name).exists():
            logger.warning("Program name %s does not exist.", program_name)
            return handle_error(
                ErrorCode.INVALID_DATA,
                ErrorMessage.PROGRAM_NAME_DOES_NOT_EXIST,
                status_code=400,
            )

        try:
            uuid.UUID(language_id)
            is_uuid = True
        except ValueError:
            is_uuid = False

        program, iso_language_code, language_page = self.get_program_and_language(
            program_name, language_id, is_uuid
        )
        if not program or not iso_language_code or not language_page:
            return handle_error(
                ErrorCode.INVALID_DATA,
                ErrorMessage.INVALID_PROGRAM_OR_LANGUAGE,
                status_code=400,
            )

        existing_product = Product.objects.filter(
            program_name=program.programme_name,
            product_title__iexact=product_title,
        ).first()
        product_key, version_number = self.get_product_key_and_version(
            program, product_title, language_id
        )
        self.mark_previous_versions_archived(existing_product, language_id)
        product_code = self.generate_unique_product_code(
            program.program_id, product_key, iso_language_code, version_number
        )

        data.update(
            {
                "title": product_title,
                "slug": slugify(product_title + str(datetime.datetime.now())),
                "product_id": product_id,
                "version_number": version_number,
                "product_code": product_code,
                "is_latest": True,
                "iso_language_code": iso_language_code,
                "program_id": program.program_id,
                "product_key": product_key,
                "file_url": file_url,
                "language_id": language_page,
                "language_name": language_page.language_names,
                "tag": tag,
                "publish_date": publish_date,
            }
        )

        parent_page = self.get_or_create_parent_page()
        user_instance = self.get_user_instance(data.get("user_id"))
        product_instance = self.create_product_instance(
            data, program, parent_page, user_instance, request
        )
        if not product_instance:
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=500,
            )
        return JsonResponse(ProductSerializer(product_instance).data, status=201)

    def get_program_and_language(self, program_name, language_id, is_uuid):
        try:
            program = Program.objects.get(programme_name=program_name)
            language_page = (
                LanguagePage.objects.get(language_id=language_id)
                if is_uuid
                else LanguagePage.objects.get(language_id__exact=language_id)
            )
            iso_language_code = language_page.iso_language_code.upper()
            logger.info(
                "Program and language found: %s (ISO: %s)",
                language_id,
                iso_language_code,
            )
            return program, iso_language_code, language_page
        except ObjectDoesNotExist as e:
            logger.warning("Program or language not found: %s", str(e))
            return None, None, None

    def get_product_key_and_version(self, program, product_title, language_id):
        product_title_ = product_title.strip()
        existing_product = Product.objects.filter(
            program_name=program.programme_name, product_title__iexact=product_title_
        ).first()
        if existing_product:
            if existing_product.language_id == language_id:
                product_key = existing_product.product_key
                version_number = existing_product.version_number + 1
            else:
                product_key = existing_product.product_key
                version_number = 1
        else:
            product_key = get_next_product_key(program.programme_name)
            version_number = 1
        logger.info("Product key: %s, Version: %d", product_key, version_number)
        return product_key, version_number

    def mark_previous_versions_archived(self, existing_product, language_id):
        if not existing_product:
            logger.info("No existing product found; no versions archived.")
            return

        # 1) Grab the instances to archive
        to_archive = list(
            Product.objects.filter(
                product_key=existing_product.product_key,
                language_id=language_id,
                is_latest=True,
            )
        )

        # 2) For each one, flip flags and .save() so your @post_save fires
        for prod in to_archive:
            prod.is_latest = False
            prod.status = "archived"
            prod.updated_at = timezone.now()
            prod.save()  # ← triggers your send_product_archived_event decorator

        logger.info(
            "Previous versions archived for product_key: %s",
            existing_product.product_key,
        )

    def generate_unique_product_code(
        self, program_id, product_key, iso_language_code, version_number
    ):
        short_program_id = str(program_id)[:5]
        short_product_key = str(product_key)[:4]
        short_language_code = iso_language_code[:4]
        product_code = f"{short_program_id}{short_product_key}{short_language_code}{version_number:03}"
        while Product.objects.filter(product_code=product_code).exists():
            version_number += 1
            product_code = f"{short_program_id}{short_product_key}{short_language_code}{version_number:03}"
        logger.info("Unique product code: %s", product_code)
        return product_code

    def get_or_create_parent_page(self):
        try:
            parent_page = Page.objects.get(slug="products")
            logger.info("Parent page 'products' found.")
        except Page.DoesNotExist:
            logger.warning("Parent page 'products' not found; creating new one.")
            root_page = Page.objects.first()
            parent_page = Page(
                title="Products",
                slug="products",
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            logger.info("Parent page 'products' created.")
        return parent_page

    def get_user_instance(self, user_ref_id):
        if user_ref_id:
            try:
                return User.objects.get(user_id=user_ref_id)
            except User.DoesNotExist as e:
                logger.warning("User %s not found: %s", user_ref_id, str(e))
                return handle_error(
                    ErrorCode.USER_NOT_FOUND,
                    ErrorMessage.USER_NOT_FOUND,
                    status_code=404,
                )
        return None

    def _is_path_collision(self, exc):
        cause = getattr(exc, "__cause__", None)
        return (
            isinstance(cause, pg_errors.UniqueViolation)
            and getattr(cause.diag, "constraint_name", "")
            == "wagtailcore_page_path_key"
        )

    def create_product_instance(
        self, data, program, parent_page, user_instance, request
    ):
        """
        Attempts up to 3 times to lock the parent and then add the new Product.
        Retries on path-key collisions.
        """
        for attempt in range(3):
            try:
                with transaction.atomic():
                    # lock the ‘products’ parent page
                    Page.objects.select_for_update().get(pk=parent_page.pk)

                    # build the Product instance
                    product_instance = Product(
                        title=data["title"],
                        slug=data["slug"],
                        product_id=data["product_id"],
                        product_title=data["title"],
                        language_id=data["language_id"],
                        language_name=data["language_name"],
                        file_url=data["file_url"],
                        is_latest=True,
                        product_key=data["product_key"],
                        iso_language_code=data["iso_language_code"],
                        product_code=data["product_code"],
                        version_number=data["version_number"],
                        user_ref=user_instance,
                        program_id=program,
                        program_name=data["program_name"],
                        tag=data["tag"],
                        publish_date=data.get("publish_date"),
                        suppress_event=False,
                    )

                    # add_child allocates path/depth, then saves
                    parent_page.add_child(instance=product_instance)
                    product_instance.save()
                    product_instance.refresh_from_db()
                    return product_instance

            except IntegrityError as exc:
                if self._is_path_collision(exc) and attempt < 2:
                    time.sleep(0.1 * (2**attempt))
                    continue
                # any other error or max attempts → log and give up
                logger.exception(
                    "Error creating product instance on attempt %d", attempt
                )
                return None

        return None


class ProductListMixin(PresignedUrlMixin):
    """
    Handles sorting, pagination + S3 presigning (both attachment and inline),
    with per-request caching of raw data list.
    """

    serializer_class = ProductSerializer
    include_request_context = False
    cache_timeout = CACHE_TTL
    pagination_class = CustomPagination

    def get_cache_key(self, request, prefix="products"):
        user_id = request.user.id if request.user.is_authenticated else "anon"
        return f"{prefix}:user:{user_id}:{request.get_full_path()}"

    def get_serializer_context(self):
        """
        Override DRF method signature: no args.
        Only include 'request' if flagged.
        """
        return {"request": self.request} if self.include_request_context else {}

    def get_sorted_queryset(self, queryset, request):
        sort_by = request.GET.get("sort_by", "").lstrip()
        if sort_by in VALID_SORT_FIELDS:
            return queryset.order_by(sort_by)
        return queryset

    def paginate_and_serialize(
        self,
        queryset,
        request,
        serializer_class=None,
        use_direct_update=False,
    ):
        """
        Returns (data_list, paginator).
        Caches only the data_list, never a Response.
        """
        cache_key = self.get_cache_key(request)
        cached = cache.get(cache_key)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)

        if cached is not None:
            return cached, paginator

        ctx = self.get_serializer_context()
        serializer = (serializer_class or self.serializer_class)(
            page, many=True, context=ctx
        )

        # 1) Gather & presign "download" URLs
        urls = extract_s3_urls(serializer.data)
        presigned = generate_presigned_urls(urls)

        # 2) Inject attachment-style presigned URLs into the serialized data
        if use_direct_update:
            _update_product_downloads_with_presigned_urls(page, presigned)
            serializer = (serializer_class or self.serializer_class)(
                page, many=True, context=ctx
            )
        else:
            update_product_urls(serializer.data, presigned)

        data = serializer.data

        # 3) Inject inline presigned URLs (and merge metadata) for every item
        for item in data:
            self._process_presigned_urls(item)

        cache.set(cache_key, data, self.cache_timeout)
        return data, paginator


@method_decorator(cache_page(CACHE_TTL), name="dispatch")
class ProductAdminListView(ProductListMixin, APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    include_request_context = True

    def get(self, request, *args, **kwargs):
        logger.info("ProductAdminListView GET called")
        try:
            qs = Product.objects.all()
            if not qs.exists():
                logger.warning(ErrorMessage.PRODUCT_NOT_FOUND.value)
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            sorted_qs = self.get_sorted_queryset(qs, request)
            data, paginator = self.paginate_and_serialize(
                sorted_qs, request, use_direct_update=True
            )
            logger.info("Returning %d products", len(data))
            return paginator.get_paginated_response(
                data, status_code=status.HTTP_200_OK
            )

        except Exception as e:
            return handle_exceptions(e)


@method_decorator(cache_page(CACHE_TTL), name="dispatch")
class ProductUsersListView(ProductListMixin, APIView):
    """
    GET /api/v1/products/users/all/
      ?page=1
      &sort_by=-created_at
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        try:
            qs = Product.objects.filter(is_latest=True, status="live").distinct()
            if not qs.exists():
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            sorted_qs = self.get_sorted_queryset(qs, request)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)

            data = filter_live_languages(data)
            return paginator.get_paginated_response(data)

        except Exception as e:
            logger.exception(f"Unhandled exception in ProductUsersListView.get, {e}")
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProductSearchListMixin(ProductListMixin):
    """
    Mixin for search endpoints. Uses ProductSearchSerializer.
    """

    serializer_class = ProductSearchSerializer


class BaseProductSearchView(APIView, ProductListMixin):
    pagination_class = CustomPagination

    def get_default_query(self) -> Q:
        return Q()

    def postprocess_response_data(self, response_data: dict, products) -> dict:
        return response_data

    def get(self, request, *args, **kwargs) -> Response:
        try:
            product_code = request.GET.get("product_code")
            product_title = request.GET.get("product_title")
            if product_code and not re.match(PRODUCT_CODE_PATTERN, product_code):
                return _handle_invalid_query_param()
            if product_title and not isinstance(product_title, str):
                return _handle_invalid_query_param()

            query = self.get_default_query()
            if product_code:
                normalized = re.sub(r"[-_]", "", product_code)
                query &= Q(product_code_no_dashes__icontains=normalized)
            if product_title:
                query &= Q(product_title__icontains=product_title)

            products = Product.objects.filter(query).distinct()
            if not products.exists():
                return Response(
                    {"detail": ErrorMessage.PRODUCT_NOT_FOUND.value},
                    status=status.HTTP_404_NOT_FOUND,
                )

            sort_by = request.GET.get("sort_by")
            allowed = {"product_title", "product_code_no_dashes"}
            if sort_by and sort_by.lstrip("-") in allowed:
                products = products.order_by(sort_by)

            data, paginator = self.paginate_and_serialize(products, request)

            response_data = _prepare_response_data(
                products, data, product_code, product_title
            )
            response_data = self.postprocess_response_data(response_data, products)

            if paginator is None:
                return Response(response_data, status=status.HTTP_200_OK)
            return paginator.get_paginated_response(
                response_data, status_code=status.HTTP_200_OK
            )

        except DatabaseError:
            return _handle_database_error()
        except TimeoutError:
            return _handle_timeout_error()
        except ValidationError:
            return _handle_invalid_query_param()
        except Exception:
            logger.exception(INTERNAL_ERROR_MSG)
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProductSearchAdminView(BaseProductSearchView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get_default_query(self) -> Q:
        return Q()

    def postprocess_response_data(self, response_data: dict, products) -> dict:
        response_data["recommended_products"] = get_recommended_products(products)
        return response_data


class ProductSearchUserView(BaseProductSearchView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get_default_query(self) -> Q:
        return Q(is_latest=True, status="live")


class ProductUsersSearchFilterAPIView(generics.ListAPIView):
    """
    GET /api/v1/products/user/search/filter/
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    serializer_class = ProductSearchSerializer
    pagination_class = CustomPagination
    queryset = Product.objects.filter(status="live", is_latest=True)

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ["product_title", "product_code_no_dashes"]
    ordering_fields = VALID_SORT_FIELDS
    ordering = ["product_title", "-updated_at"]


class ProductUsersFilterView(ProductListMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        try:
            base_q = Q(is_latest=True, status="live")
            filters = Q()

            dl = request.GET.get("download_only", "").lower()
            do = request.GET.get("download_or_order", "").lower()
            oo = request.GET.get("order_only", "").lower()
            if dl == "true":
                filters &= Q(tag="download_only")
            elif do == "true":
                filters &= Q(tag="download_and_order")
            elif oo == "true":
                filters &= Q(tag="order_only")

            for param, lookup in [
                ("audiences", "update_ref__audience_ref__name"),
                ("diseases", "update_ref__diseases_ref__name"),
                ("vaccinations", "update_ref__vaccination_ref__name"),
                ("program_names", "program_name"),
                ("where_to_use", "update_ref__where_to_use_ref__name"),
                ("alternative_type", "update_ref__alternative_type"),
                ("product_type", "update_ref__product_type"),
                ("languages", "language_name"),
            ]:
                vals = request.GET.getlist(param)
                if vals:
                    filters &= Q(**{f"{lookup}__in": vals})

            if recent := request.GET.get("recently_updated"):
                try:
                    filters &= Q(updated_at__gte=recent)
                except ValueError:
                    return handle_error(
                        ErrorCode.INVALID_PARAMETER,
                        f"Invalid date for recently_updated: {recent}",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )

            queryset = Product.objects.filter(base_q & filters).distinct()
            sorted_qs = self.get_sorted_queryset(queryset, request)

            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            data = filter_live_languages(data)
            return paginator.get_paginated_response(data)

        except Exception:
            logger.exception(INTERNAL_ERROR_MSG)
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProductAdminFilterView(ProductListMixin, APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def _build_filter_query(self, request):
        mapping = {
            "diseases": "update_ref__diseases_ref__name__in",
            "vaccinations": "update_ref__vaccination_ref__name__in",
            "audiences": "update_ref__audience_ref__name__in",
            "where_to_use": "update_ref__where_to_use_ref__name__in",
            "alternative_type": "update_ref__alternative_type__in",
            "product_type": "update_ref__product_type__in",
            "languages": "language_name__in",
            "access_type": "tag__in",
            "status": "status__in",
        }
        q = Q()
        for param, lookup in mapping.items():
            vals = request.GET.getlist(param, [])
            if vals:
                q &= Q(**{lookup: vals})

        codes = request.GET.getlist("product_code")
        if codes:
            code_q = Q()
            for c in codes:
                normalized = re.sub(r"[-_]", "", c)
                code_q |= Q(product_code_no_dashes__icontains=normalized)
            q &= code_q

        return q

    def get(self, request, *args, **kwargs) -> Response:
        try:
            base_q = self._build_filter_query(request)
            qs = Product.objects.filter(base_q).distinct()
            sorted_qs = self.get_sorted_queryset(qs, request)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            return paginator.get_paginated_response(data)
        except Exception:
            logger.exception(INTERNAL_ERROR_MSG)
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProgramProductsView(ProductListMixin, generics.ListAPIView):
    """
    GET /api/v1/programmes/<program_id>/products/
    """

    serializer_class = ProductSerializer
    pagination_class = CustomPagination
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    cache_timeout = CACHE_TTL

    def get_cache_key(self, request, program_id):
        user_id = request.user.id if request.user.is_authenticated else "anon"
        return f"prog_products:{program_id}:user:{user_id}:{request.get_full_path()}"

    def get_queryset(self):
        program = get_object_or_404(Program, pk=self.kwargs["program_id"])
        diseases = Disease.objects.filter(programs=program)
        vaccinations = Vaccination.objects.filter(programs=program)
        return (
            Product.objects.select_related("update_ref")
            .prefetch_related(
                "update_ref__diseases_ref",
                "update_ref__vaccination_ref",
            )
            .filter(
                Q(program_id=program.pk),
                Q(update_ref__diseases_ref__in=diseases)
                | Q(update_ref__vaccination_ref__in=vaccinations),
                Q(is_latest=True),
                Q(status="live"),
            )
            .distinct()
        )

    def list(self, request, *args, **kwargs):
        cache_key = self.get_cache_key(request, kwargs["program_id"])
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        response = super().list(request, *args, **kwargs)

        all_urls = extract_s3_urls(response.data["results"])
        presigned = generate_presigned_urls(all_urls)
        update_product_urls(response.data["results"], presigned)

        program = get_object_or_404(Program, pk=kwargs["program_id"])
        response.data["diseases"] = DiseaseSerializer(
            Disease.objects.filter(programs=program), many=True
        ).data
        response.data["vaccinations"] = VaccinationSerializer(
            Vaccination.objects.filter(programs=program), many=True
        ).data

        cache.set(cache_key, response.data, self.cache_timeout)
        return response


class IncompleteProductsView(View):
    def get(self, request, *args, **kwargs):
        current = timezone.now().date()
        ahead = current + timedelta(days=7)
        drafts = Product.objects.filter(
            status="draft",
            publish_date__gt=current,
            publish_date__lte=ahead,
        )
        logger.info("Found %d draft products publishing within 7 days", drafts.count())

        checker = ProductStatusUpdateView()
        incomplete = []
        for p in drafts:
            missing = checker.check_required_fields(p)
            if missing:
                incomplete.append(
                    {
                        "tag": p.tag,
                        "product_title": p.product_title,
                        "product_code": p.product_code,
                    }
                )

        return JsonResponse(incomplete, safe=False)
