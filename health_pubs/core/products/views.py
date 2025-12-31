from collections import defaultdict
import datetime
import hashlib
import json
import logging
import re
import os
import uuid
import difflib
from typing import Any, Iterable, Mapping, Optional, Set, Union, Dict, List, Tuple
from urllib.parse import unquote, urlsplit, parse_qsl, urlencode
from django.utils import timezone
import time
from django.db import IntegrityError
from django.core.cache import cache
from psycopg2 import errors as pg_errors
from datetime import timedelta

from django.db.models import (
    Q,
    Max,
    F,
    Value,
    IntegerField,
    OuterRef,
    Subquery,
    Case,
    When,
    TextField,
)
from django.db.models.functions import (
    Upper,
    Trim,
    Replace,
    Concat,
)

import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from core.audiences.models import Audience
from core.diseases.models import Disease
from core.diseases.serializers import DiseaseSerializer
from core.errors.enums import ErrorCode, ErrorMessage
from core.errors.error_function import handle_error
from core.languages.models import LanguagePage
from core.order_limits.models import OrderLimitPage
from core.organizations.models import Organization
from core.programs.models import Program
from core.users.models import User
from core.users.permissions import (
    IsAdminUser,
)
from core.establishments.models import Establishment
from core.utils.custom_token_authentication import CustomTokenAuthentication
from core.utils.extract_file_metadata import get_file_metadata
from core.utils.generate_s3_presigned_url import (
    generate_inline_presigned_urls,
    generate_presigned_urls,
)
from .filters import ProductFilter
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.filters import OrderingFilter, SearchFilter
from django_filters.rest_framework import DjangoFilterBackend
from django.conf import settings
from django.core.cache import cache

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
from django.utils.http import http_date
from rest_framework.views import APIView
from wagtail.models import Page
from collections.abc import Mapping
from django.http import HttpRequest
from .models import Product, ProductUpdate
from .serializers import (
    ProductSearchSerializer,
    ProductSerializer,
    ProductUpdateSerializer,
    RelatedProductSerializer,
    AdminProductSerializer,
)
from wagtail.models import Page
from treebeard.mp_tree import MP_Node
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


# --------------------------------------------------------------------------- #
# Global constant for valid sort fields                                       #
# --------------------------------------------------------------------------- #
VALID_SORT_FIELDS: List[str] = [
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


# Expandable internal allow-list we’ll reuse everywhere
ALLOWED_SORT_FIELDS: set[str] = set(
    VALID_SORT_FIELDS
    + [
        "norm_code",
        "-norm_code",
        "product_code_no_dashes",
        "-product_code_no_dashes",
        "program_name",
        "-program_name",
    ]
)


_DIGITS = list("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")
_BASE = len(_DIGITS)

_DIGIT_MAP = {ch: i for i, ch in enumerate(_DIGITS)}
_VALID_KEY_RE = re.compile(r"^[A-Z0-9]+$")
# default TTLs (in seconds)
CACHE_TTL = getattr(settings, "CACHE_TTL")

# Remove hyphens, underscores, and whitespace, then uppercase.
PRODUCT_CODE_NORMALIZE_RE = re.compile(r"[-_\s]+")

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


def normalize_product_code(value: str) -> str:
    """Normalize a product code the same way as DB normalization."""
    if not value:
        return ""
    return PRODUCT_CODE_NORMALIZE_RE.sub("", value).upper()


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


def _normalize_key(key: str) -> str:
    if key is None:
        return ""
    return str(key).strip().upper()


def _key_to_int(key: str) -> int:
    """
    Convert a base-36-like key (A-Z,0-9) into an integer.
    Raises ValueError for invalid tokens (callers should pre-filter).
    """
    s = _normalize_key(key)
    if not s or not _VALID_KEY_RE.match(s):
        raise ValueError(f"invalid product_key '{key}'")
    value = 0
    for ch in s:
        value = value * _BASE + _DIGIT_MAP[ch]
    return value


def get_next_product_key(program_name: str) -> str:
    """
    Fetch existing keys for this program, ignore malformed ones,
    and compute the next key from the max valid key.
    """
    keys_qs = Product.objects.filter(program_name=program_name).values_list(
        "product_key", flat=True
    )

    valid_keys, invalid_keys = [], []
    for raw in keys_qs:
        s = _normalize_key(raw)
        if s and _VALID_KEY_RE.match(s):
            valid_keys.append(s)
        else:
            invalid_keys.append(raw)

    if invalid_keys:
        logging.warning(
            "get_next_product_key: ignoring %d invalid product_key(s) for program '%s' "
            "(showing up to 5): %s",
            len(invalid_keys),
            program_name,
            invalid_keys[:5],
        )

    last = max(valid_keys, key=_key_to_int) if valid_keys else None
    next_key = generate_product_key(last)  # should handle None
    logging.info(
        "get_next_product_key: %r → %r (from %d valid keys)",
        last,
        next_key,
        len(valid_keys),
    )
    return next_key


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


# --------------------------------------------------------------------------- #
# Helper: invalidate caches after write                                       #
# --------------------------------------------------------------------------- #


def invalidate_product_caches(product_code: str | None = None):
    """
    Optional: If your cache backend supports pattern deletes (e.g., django-redis),
    this purges list caches and the detail cache for the product.
    If not supported, the short TTLs still keep things fresh quickly.
    """
    try:
        cache.delete_pattern("products:*")  # list/search
        cache.delete_pattern("prog_products:*")  # program lists (if used)
        if product_code:
            cache.delete_pattern(f"product_detail:*:{product_code}")
    except AttributeError:
        # Backend doesn't support delete_pattern — rely on TTL.
        pass


# --------------------------------------------------------------------------- #
# Function: build_admin_queryset                                               #
# --------------------------------------------------------------------------- #


def build_admin_queryset(request, *, apply_filters: bool = False):
    """
    Build queryset for admin list/filter views.
    Includes:
    - faceted filters
    - product code & title filters
    - publish_date filters
    - last_updated_by (latest editor)
    - created_by (original author)
    """

    # --------------------------------------------
    # Faceted filters
    # --------------------------------------------
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
        "program_names": "program_name__in",
        "program_ids": "program_id__in",
    }

    q = Q()

    # ============================================================
    # APPLY FILTERS
    # ============================================================
    if apply_filters:
        # --------------------------------------------
        # Faceted filters
        # --------------------------------------------
        for param, lookup in mapping.items():
            vals = request.GET.getlist(param, [])
            if vals:
                q &= Q(**{lookup: vals})

        # --------------------------------------------
        # Product Code Filter
        # --------------------------------------------
        codes = request.GET.getlist("product_code")
        if codes:
            code_q = Q()
            for c in codes:
                norm = re.sub(r"[-_\s]+", "", c).upper().strip()
                code_q |= Q(product_code__icontains=c) | Q(
                    product_code_no_dashes__icontains=norm
                )
            q &= code_q

        # --------------------------------------------
        # Product Title Filter
        # --------------------------------------------
        titles = request.GET.getlist("product_title")
        if titles:
            title_q = Q()
            for t in titles:
                clean = (t or "").strip()
                if clean:
                    title_q |= Q(product_title__icontains=clean)
            if title_q:
                q &= title_q

        # --------------------------------------------
        # PUBLISH DATE FILTERS
        # --------------------------------------------
        def _parse_date(val: str | None):
            val = (val or "").strip()
            if not val:
                return None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
                try:
                    return datetime.datetime.strptime(val, fmt).date()
                except ValueError:
                    pass
            logger.warning("Invalid publish_date value %r – ignored", val)
            return None

        exact = _parse_date(request.GET.get("publish_date"))
        date_from = _parse_date(request.GET.get("publish_date_from"))
        date_to = _parse_date(request.GET.get("publish_date_to"))

        if exact:
            q &= Q(publish_date=exact)
        else:
            if date_from:
                q &= Q(publish_date__gte=date_from)
            if date_to:
                q &= Q(publish_date__lte=date_to)

    # ============================================================
    # BASE QUERYSET
    # ============================================================
    qs = Product.objects.filter(q).select_related(
        "program_id",
        "language_id",
        "update_ref",
        "user_ref",
    )

    # ============================================================
    # ANNOTATE ORIGINAL CREATOR (first Product)
    # ============================================================
    creator_user_subquery = (
        Product.objects.filter(
            product_key=OuterRef("product_key"),
            language_id=OuterRef("language_id"),
        )
        .order_by("created_at", "version_number", "id")
        .values("user_ref__user_id")[:1]
    )

    creator_name_subquery = (
        User.objects.filter(user_id=OuterRef("creator_user_id"))
        .annotate(full_name=Concat(F("first_name"), Value(" "), F("last_name")))
        .values("full_name")[:1]
    )

    qs = qs.annotate(
        creator_user_id=Subquery(creator_user_subquery, output_field=TextField()),
        creator_display_name=Subquery(creator_name_subquery, output_field=TextField()),
    )

    # ============================================================
    # ANNOTATE LAST MODIFIED BY (latest Product)
    # ============================================================
    modifier_user_subquery = (
        Product.objects.filter(
            product_key=OuterRef("product_key"),
            language_id=OuterRef("language_id"),
        )
        .order_by("-updated_at", "-version_number", "-id")
        .values("user_ref__user_id")[:1]
    )

    modifier_name_subquery = (
        User.objects.filter(user_id=OuterRef("modifier_user_id"))
        .annotate(full_name=Concat(F("first_name"), Value(" "), F("last_name")))
        .values("full_name")[:1]
    )

    qs = qs.annotate(
        modifier_user_id=Subquery(modifier_user_subquery, output_field=TextField()),
        modifier_display_name=Subquery(
            modifier_name_subquery, output_field=TextField()
        ),
    )

    # ============================================================
    # CREATED BY FILTER — supports:
    #  - ?created_by=me
    #  - ?created_by=user_id (partial)
    #  - ?created_by=first/last/full name (partial)
    # ============================================================
    created_vals = request.GET.getlist("created_by", [])
    if created_vals:
        cb_q = Q()
        current = getattr(request, "user", None)

        for raw_val in created_vals:
            token = (raw_val or "").strip()
            if not token:
                continue

            if token.lower() == "me" and current and current.is_authenticated:
                cb_q |= Q(creator_user_id=current.user_id)
                continue

            cb_q |= Q(creator_user_id__icontains=token)
            cb_q |= Q(creator_display_name__icontains=token)

        qs = qs.filter(cb_q)

    # ============================================================
    # LAST MODIFIED BY FILTER — same pattern as CREATED BY
    # ============================================================
    modified_vals = request.GET.getlist("last_updated_by", [])
    if modified_vals:
        lm_q = Q()
        current = getattr(request, "user", None)

        for raw_val in modified_vals:
            token = (raw_val or "").strip()
            if not token:
                continue

            if token.lower() == "me" and current and current.is_authenticated:
                lm_q |= Q(modifier_user_id=current.user_id)
                continue

            lm_q |= Q(modifier_user_id__icontains=token)
            lm_q |= Q(modifier_display_name__icontains=token)

        qs = qs.filter(lm_q)

    return qs


class CustomPagination(PageNumberPagination):
    page_size = getattr(
        settings, "PRODUCTS_PAGE_SIZE", 10
    )  # Set pagination to 10 items per page

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


class AdminPagination(CustomPagination):
    # Only the admin list should use this larger/smaller page size
    page_size = getattr(settings, "ADMIN_PRODUCTS_PAGE_SIZE", 25)  # pick your number


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
    DATE_INPUT_FORMATS = ("%Y-%m-%d", "%m/%d/%Y")
    DATETIME_INPUT_FORMATS = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
    )
    DATE_SENTINELS = {"immediately", "no_end_date", "specific_date"}

    # ------------------------------------------------------------------ #
    # Low-level normalization helpers                                     #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _none_if_na(value: Any) -> Any:
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

    def _clean_invalid_strings(self, row: Dict[str, Any]) -> Dict[str, Any]:
        SENTINELS = {"-", "nan", "n/a", "na"}
        for key, val in row.items():
            if isinstance(val, str) and val.strip().lower() in SENTINELS:
                row[key] = None
        return row

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
                return str(int(float(value)))
        except Exception:
            logger.exception("Error normalising numeric field %r", value)
        return None

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

    @classmethod
    def _coerce_date(cls, value: Any) -> Optional[datetime.date]:
        value = cls._none_if_na(value)
        if value is None:
            return None
        if isinstance(value, (pd.Timestamp, datetime.datetime)):
            return value.date()
        if isinstance(value, datetime.date) and not isinstance(
            value, datetime.datetime
        ):
            return value
        if isinstance(value, str):
            if value.strip().lower() in cls.DATE_SENTINELS:
                return None
            for fmt in cls.DATE_INPUT_FORMATS:
                try:
                    return datetime.datetime.strptime(value, fmt).date()
                except ValueError:
                    continue
        logger.warning("Could not parse date %r — defaulting to today()", value)
        return datetime.date.today()

    @classmethod
    def _coerce_datetime(cls, value: Any) -> datetime.datetime:
        value = cls._none_if_na(value)
        if isinstance(value, pd.Timestamp):
            dt = value.to_pydatetime()
        elif isinstance(value, datetime.datetime):
            dt = value
        elif isinstance(value, str):
            for fmt in cls.DATETIME_INPUT_FORMATS:
                try:
                    dt = datetime.datetime.strptime(value, fmt)
                    break
                except ValueError:
                    continue
            else:
                logger.warning("Unsupported datetime %r — using now()", value)
                dt = timezone.now()
        else:
            dt = timezone.now()

        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_default_timezone())
        return dt

    # ------------------------------------------------------------------ #
    # New small helpers used to reduce complexity in key methods         #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _bool_from_str(value: Any) -> bool:
        return str(value or "").strip().lower() in {"y", "yes", "true", "1"}

    @staticmethod
    def _normalize_choice(val: Any, mapping: Dict[str, str]) -> Optional[str]:
        if not isinstance(val, str):
            return None
        return mapping.get(val.strip().lower())

    def _get_valid_product_types(self) -> List[str]:
        try:
            choices = ProductUpdate._meta.get_field("product_type").choices
            return [val for val, _ in choices]
        except Exception:
            return []

    # ---- tiny helpers for product_type normalization ----
    @staticmethod
    def _to_clean_lower(raw: Any) -> Optional[str]:
        """Return a stripped, lowercase string or None."""
        if not isinstance(raw, str):
            return None
        s = raw.strip()
        return s.lower() if s else None

    def _build_product_type_lookup(self) -> Dict[str, str]:
        """
        Build a case-insensitive lookup of valid product types.
        Also maps naïve singular/plural toggles to the canonical choice.
        """
        lookup: Dict[str, str] = {}
        for choice in self._get_valid_product_types():
            c_low = choice.lower()
            lookup[c_low] = choice
            # naive plural/singular bridging
            if c_low.endswith("s"):
                lookup[c_low[:-1]] = choice  # singular maps to canonical
            else:
                lookup[c_low + "s"] = choice  # plural maps to canonical
        return lookup

    def _normalize_product_type(self, raw: Any) -> Optional[str]:
        """
        Return the canonical product_type (matching model choices) or None.
        Complexity reduced by using a precomputed lookup.
        """
        val = self._to_clean_lower(raw)
        if not val:
            return None

        # If choices not available, bail early
        valid_lookup = self._build_product_type_lookup()
        if not valid_lookup:
            return None

        return valid_lookup.get(val)

    def _clean_numeric_columns(self, row: Dict[str, Any], cols: set) -> None:
        for col in cols:
            row[col] = self._clean_numeric_field(row.get(col))

    def _coerce_row_dates(self, row: Dict[str, Any], cols: Iterable[str]) -> None:
        for col in cols:
            row[col] = self._coerce_date(row.get(col))

    @staticmethod
    def _set_email_aliases(row: Dict[str, Any]) -> None:
        if row.get("stock_owner"):
            row["stock_owner_email_address"] = row.get("stock_owner")
        if row.get("stock_referral"):
            row["order_referral_email_address"] = row.get("stock_referral")

    # -------- Helpers for create_order_limits --------
    @staticmethod
    def _default_limits() -> Dict[str, int]:
        return {
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

    def _parse_supplied_limits(self, row: Mapping[str, Any]) -> Dict[str, int]:
        supplied: Dict[str, int] = {}
        raw_names = row.get("organization_names")
        sheet_limit = row.get("order_limit_value")
        if raw_names and sheet_limit not in (None, ""):
            try:
                limit_val = int(str(sheet_limit).strip())
                for name in str(raw_names).split(","):
                    nm = name.strip()
                    if nm:
                        supplied[nm] = limit_val
            except ValueError:
                logger.warning(
                    "Invalid order_limit_value %r — skipping explicit limits",
                    sheet_limit,
                )
        return supplied

    @staticmethod
    def _lookup_org_by_name(name: str):
        # Case-insensitive lookup, but we will use the exact DB value (org.name)
        return Organization.objects.filter(name__iexact=name).first()

    def _create_order_limit_page(
        self, product: "Product", org: "Organization", lim_val: int
    ) -> bool:
        # idempotency guard — avoid duplicates
        if OrderLimitPage.objects.filter(
            product_ref=product, organization_ref=org
        ).exists():
            return False
        ol = OrderLimitPage(
            title=f"Order limit for {org.name}",
            slug=f"ol-{org.id}-{uuid.uuid4().hex[:6]}",
            order_limit_id=str(uuid.uuid4()),
            order_limit=lim_val,
            product_ref=product,
            organization_ref=org,
        )
        res = self.safe_add_child(product, ol)
        if isinstance(res, dict) and res.get("skip"):
            return False
        return True

    # -------- Helpers for _process_row --------
    @staticmethod
    def _normalize_tag_and_status(row: Dict[str, Any]) -> Tuple[str, bool, bool]:
        tag_raw = row.get("tag") or ""
        normalized_tag = normalize_tag(str(tag_raw))
        row["tag"] = normalized_tag
        status_val = str(row.get("status") or "").strip().lower()
        is_download_only = normalized_tag == "download-only"
        is_live = status_val == "live"
        return normalized_tag, is_download_only, is_live

    def _try_update_existing_product(
        self,
        code: Optional[str],
        row: Mapping[str, Any],
        is_live: bool,
        is_download_only: bool,
        m2m_map: Dict[str, Tuple[str, Any, str, str]],
    ) -> Optional[Dict[str, Any]]:
        if not code:
            return None

        existing = Product.objects.filter(product_code=code).first()
        if not existing:
            return None

        SIMPLE_FIELDS = [
            "title",
            "status",
            "file_url",
            "tag",
            "product_key",
            "language_name",
            "publish_date",
        ]
        for field in SIMPLE_FIELDS:
            incoming_key = {
                "file_url": "gov_related_article",
                "summary_of_guidance": "guidance",
            }.get(field, field)
            incoming = row.get(incoming_key)
            if incoming is not None and not getattr(existing, field):
                setattr(existing, field, incoming)
        existing.save()

        if existing.update_ref:
            self.assign_m2m_fields(existing.update_ref, m2m_map, row, add_only=True)

        order_limits_created = 0
        if is_live and not is_download_only:
            ols = self.create_order_limits(existing, row)
            order_limits_created = len(ols)

        return {
            "skip": False,
            "updated": True,
            "order_limits": order_limits_created,
            "warnings": [],
            "errors": [],
        }

    def _collect_expected_required_fields(
        self, row: Mapping[str, Any], is_live: bool, is_download_only: bool
    ) -> Set[str]:
        if not is_live:
            return set()

        if is_download_only:
            expected = {
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
            expected = {
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
            if self._must_have_order_until(row):
                expected.add("order_until_date")
        return expected

    @staticmethod
    def _is_missing(val: Any) -> bool:
        return val is None or (isinstance(val, str) and not val.strip())

    def _validate_missing_fields(
        self,
        idx: int,
        row: Mapping[str, Any],
        expected_required: Set[str],
        warnings: List[str],
    ) -> None:
        missing = [f for f in expected_required if self._is_missing(row.get(f))]
        if missing:
            msg = f"Row {idx+1} missing expected fields: {', '.join(sorted(missing))}"
            logger.warning(msg)
            warnings.append(msg)

    def _resolve_foreign_keys(
        self, row: Mapping[str, Any], is_live: bool, warnings: List[str]
    ) -> Tuple[Optional["Program"], Optional["LanguagePage"], str]:
        program = None
        pid = row.get("programme_id")
        if pid:
            program = Program.objects.filter(program_id=str(pid)).first()
            if is_live and not program:
                msg = f"Program {pid} not found"
                logger.warning(msg)
                warnings.append(msg)

        language = None
        lid = row.get("language_id")
        if lid:
            language = LanguagePage.objects.filter(language_id=lid).first()
            if is_live and not language:
                msg = f"Language {lid} not found"
                logger.warning(msg)
                warnings.append(msg)

        iso_code = language.iso_language_code if language else ""
        return program, language, iso_code

    def _attach_pu_and_product(
        self,
        row: Mapping[str, Any],
        root: "Page",
        m2m_map: Dict[str, Tuple[str, Any, str, str]],
        program: Optional["Program"],
        language: Optional["LanguagePage"],
        iso_code: str,
        created_dt: datetime.datetime,
        pub_date: datetime.date,
        is_live: bool,
        is_download_only: bool,
    ) -> Tuple[bool, int, List[str], List[str]]:
        warnings: List[str] = []
        errors: List[str] = []
        order_limits_created = 0
        created = False

        pu = self.create_product_update(row)
        res_pu = self.safe_add_child(root, pu)
        if isinstance(res_pu, dict) and res_pu.get("skip"):
            error = "Failed to attach ProductUpdate"
            logger.error(error)
            errors.append(error)
            return created, order_limits_created, warnings, errors

        pu = res_pu
        self.assign_m2m_fields(pu, m2m_map, row, add_only=False)

        prod = self.create_product(
            row, program, language, iso_code, pu, created_dt, pub_date
        )
        try:
            prod.full_clean()
        except ValidationError as ve:
            warning = f"Product validation warnings: {ve}"
            logger.warning(warning)
            warnings.append(warning)

        res_prod = self.safe_add_child(pu, prod)
        if isinstance(res_prod, dict) and res_prod.get("skip"):
            error = "Failed to attach Product"
            logger.error(error)
            errors.append(error)
            return created, order_limits_created, warnings, errors

        prod = res_prod
        if is_live and not is_download_only:
            ols = self.create_order_limits(prod, row)
            order_limits_created = len(ols)
        created = True

        return created, order_limits_created, warnings, errors

    # ------------------------------------------------------------------ #
    # Refactored: clean_row_data (<= 15)                                  #
    # ------------------------------------------------------------------ #
    def clean_row_data(self, row: Mapping[str, Any]) -> Dict[str, Any]:
        # base cleaning
        row = {k: self._none_if_na(v) for k, v in row.items()}
        row = self._clean_invalid_strings(row)

        # booleans & enums
        row["run_to_zero"] = self._bool_from_str(row.get("run_to_zero"))
        row["product_type"] = self._normalize_product_type(row.get("product_type"))

        if row.get("alternative_type") is not None:
            alt = str(row["alternative_type"]).strip()
            row["alternative_type"] = alt or None

        row["available_from_choice"] = self._normalize_choice(
            row.get("available_from_choice") or row.get("available_from_date"),
            {"immediately": "immediately", "specific_date": "specific_date"},
        )
        row["available_until_choice"] = self._normalize_choice(
            row.get("available_until_choice") or row.get("available_until_date"),
            {"no_end_date": "no_end_date", "specific_date": "specific_date"},
        )

        # numerics
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
        self._clean_numeric_columns(row, NUMERIC_COLS)

        # codes
        row["local_code"] = self._clean_local_code(row.get("local_code"))
        row["cost_centre"] = self._clean_alphanumeric_code(row.get("cost_centre"))

        # dates
        row["created"] = self._coerce_datetime(row.get("created"))
        row["version_date"] = self._coerce_date(row.get("version_date"))
        self._coerce_row_dates(
            row, ("order_from_date", "order_until_date", "order_end_date")
        )

        # email aliases
        self._set_email_aliases(row)

        logger.debug("Cleaned row data: %s", row)
        return row

    # ------------------------------------------------------------------ #
    # Unchanged: Wagtail-safe add_child                                   #
    # ------------------------------------------------------------------ #
    def safe_add_child(self, parent: Page, instance: Page) -> Page:
        try:
            return parent.add_child(instance=instance)
        except AttributeError as exc:
            if "'NoneType' object has no attribute '_inc_path'" in str(exc):
                logger.info(
                    "Parent %r has no children yet; assigning first-child path manually",
                    parent,
                )
                token_size = getattr(MP_Node, "_path_step", 4)
                seg = str(1).zfill(token_size)
                instance.depth = parent.depth + 1
                instance.path = parent.path + seg
                instance.save()
                return instance
            raise

    # ------------------------------------------------------------------ #
    # Unchanged: factories                                                #
    # ------------------------------------------------------------------ #
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
            order_end_date=row.get("order_until_date") or row.get("order_end_date"),
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

        slug_base = str(row.get("title") or "")
        return Product(
            title=slug_base,
            slug=f"{slugify(slug_base)}-{uuid.uuid4().hex[:6]}",
            user_ref=user,
            product_id=str(uuid.uuid4()),
            program_name=(program.programme_name if program else ""),
            product_title=slug_base,
            status=row.get("status"),
            product_code=row.get("product_code").strip(),
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

    # ------------------------------------------------------------------ #
    # Refactored: create_order_limits (<= 15)                             #
    # ------------------------------------------------------------------ #
    def create_order_limits(
        self, product: "Product", row: Mapping[str, Any]
    ) -> List[str]:
        saved: List[str] = []
        supplied = self._parse_supplied_limits(row)
        defaults = self._default_limits()

        # 1) Explicit/supplied limits from sheet
        for nm, lim_val in supplied.items():
            org = self._lookup_org_by_name(nm)
            if not org:
                logger.warning("Organization %r not found — skipping", nm)
                continue
            if self._create_order_limit_page(product, org, lim_val):
                # Use the exact DB value (no case mutation)
                saved.append(org.name)

        # 2) Fill in defaults for any organizations not explicitly supplied
        for nm, lim_val in defaults.items():
            if nm in supplied:
                continue
            org = self._lookup_org_by_name(nm)
            if not org:
                logger.warning("Organization %r not found — skipping default", nm)
                continue
            if self._create_order_limit_page(product, org, lim_val):
                saved.append(org.name)

        return saved

    # ------------------------------------------------------------------ #
    # Root and conditions                                                 #
    # ------------------------------------------------------------------ #
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

    def _must_have_order_until(self, row: Mapping[str, Any]) -> bool:
        return str(row.get("available_until_choice") or "").lower() == "specific_date"

    # ------------------------------------------------------------------ #
    # Refactored: _process_row (<= 15)                                    #
    # ------------------------------------------------------------------ #
    def _process_row(
        self,
        idx: int,
        row: Mapping[str, Any],
        root: Page,
        m2m_map: Dict[str, Tuple[str, Any, str, str]],
    ) -> Dict[str, Any]:
        warnings: List[str] = []
        errors: List[str] = []
        created = False
        updated = False
        order_limits_created = 0

        try:
            # normalize tag/status and email aliases
            self._set_email_aliases(row)
            normalized_tag, is_download_only, is_live = self._normalize_tag_and_status(
                row
            )

            logger.debug(
                "Processing row %d: tag=%s, is_download_only=%s, is_live=%s; row=%r",
                idx + 1,
                normalized_tag,
                is_download_only,
                is_live,
                row,
            )

            # If product already exists by exact code, update it and return
            code = row.get("product_code").strip() if row.get("product_code") else None
            handled = self._try_update_existing_product(
                code, row, is_live, is_download_only, m2m_map
            )
            if handled:
                handled["warnings"].extend(warnings)
                handled["errors"].extend(errors)
                return handled

            # Validate required fields (collect warnings only)
            expected = self._collect_expected_required_fields(
                row, is_live, is_download_only
            )
            self._validate_missing_fields(idx, row, expected, warnings)

            # Timestamps
            created_dt = self._coerce_datetime(row.get("created"))
            pub_date = (
                self._coerce_date(row.get("version_date")) or datetime.date.today()
            )

            # Resolve FKs
            program, language, iso_code = self._resolve_foreign_keys(
                row, is_live, warnings
            )

            # Create PU -> Product, assign M2M, OLs
            created, order_limits_created, w2, e2 = self._attach_pu_and_product(
                row=row,
                root=root,
                m2m_map=m2m_map,
                program=program,
                language=language,
                iso_code=iso_code,
                created_dt=created_dt,
                pub_date=pub_date,
                is_live=is_live,
                is_download_only=is_download_only,
            )
            warnings.extend(w2)
            errors.extend(e2)

        except Exception as exc:
            logger.exception("Row %d unexpected error", idx + 1)
            errors.append(str(exc))

        return {
            "skip": False,
            "created": created,
            "updated": updated,
            "order_limits": order_limits_created,
            "warnings": warnings,
            "errors": errors,
        }

    # ------------------------------------------------------------------ #
    # NEW: external-key based defaults (robust backfill)                 #
    # ------------------------------------------------------------------ #
    @staticmethod
    def _default_limits_by_external() -> Dict[str, int]:
        """
        Map Organization.external_key -> default limit.
        Based on your DB:
          NH (NHS), VS (Voluntary Service), LG, SH, GV, ED, PH, PC, SC, PRI.
        Excludes CR/CRC intentionally.
        """
        return {
            "NH": 500,  # NHS
            "VS": 100,  # Voluntary Service
            "LG": 500,  # Local Government
            "SH": 100,  # Stake Holder
            "GV": 100,  # Government
            "ED": 100,  # Education
            "PH": 5,  # Private Health
            "PC": 5,  # Private Company
            "SC": 500,  # Social Care
            "PRI": 5,  # Private
        }

    def ensure_default_order_limits(self, product: "Product") -> List[str]:
        """
        Create any missing defaults for this product using Organization.external_key.
        Returns list of created organization names (idempotent).
        """
        created: List[str] = []
        defaults = self._default_limits_by_external()

        # orgs already present for this product
        existing_org_ids = set(
            OrderLimitPage.objects.filter(product_ref=product).values_list(
                "organization_ref_id", flat=True
            )
        )

        # candidate orgs by external_key
        target_orgs = list(
            Organization.objects.filter(external_key__in=list(defaults.keys()))
        )

        for org in target_orgs:
            if org.id in existing_org_ids:
                continue
            lim = defaults.get(org.external_key)
            if lim is None:
                continue
            if self._create_order_limit_page(product, org, lim):
                created.append(org.name)

        return created


# ------------------------------------------------------------------ #
# Main ViewSet  : Product Bulk Upload, Related Publications           #
# ------------------------------------------------------------------ #
class ProductViewSet(ProductUtilsMixin, viewsets.ViewSet):
    authentication_classes: List = []
    permission_classes: List = []

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request: HttpRequest):
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
        created, updated, order_limits = 0, 0, 0
        for idx, row_series in df.iterrows():
            row = self.clean_row_data(row_series.to_dict())
            try:
                with transaction.atomic():
                    result = self._process_row(idx, row, root, m2m_map)
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
                updated += 1
            elif result.get("created"):
                created += 1
            order_limits += result.get("order_limits", 0)

            # 7. Log every row that neither created nor updated
            if not result.get("created") and not result.get("updated"):
                log_path = os.path.join(settings.BASE_DIR, "products_not_created.log")
                os.makedirs(os.path.dirname(log_path), exist_ok=True)
                with open(log_path, "a", encoding="utf-8") as fh:
                    fh.write(
                        json.dumps(
                            {
                                "row": idx + 1,
                                "product_code": row.get("product_code"),
                                "warnings": result.get("warnings", []),
                                "errors": result.get("errors", []),
                            }
                        )
                        + "\n"
                    )

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
                "created_products": created,
                "updated_products": updated,
                "order_limits_created": order_limits,
                "row_summary": summary,
            },
            status=status.HTTP_201_CREATED,
        )

    @staticmethod
    def _load_dataframe(request: HttpRequest):
        file = request.FILES.get("product_excel")
        if not file:
            return None, Response(
                {"error": "No Excel file uploaded (field 'product_excel')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            file.seek(0)
            df = pd.read_excel(file, engine="openpyxl", keep_default_na=True)
            df = df.replace({pd.NA: None, pd.NaT: None})
            df = df.where(pd.notna(df), None)
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
        Return related publications grouped by product_type, with up to 2 per group,
        and a 'has_more' flag indicating if more related items exist.
        """
        try:
            product = Product.objects.get(product_code=product_code)
        except Product.DoesNotExist:
            return Response({"error": "Product not found."}, status=404)

        product_update = product.update_ref
        if not product_update:
            return Response(
                {"error": "No associated product update found."}, status=404
            )

        # Find same disease/topic
        disease_ids = list(
            product_update.diseases_ref.values_list("disease_id", flat=True)
        )
        disease_ids = list(map(str, disease_ids))  # ensure correct type

        products = (
            Product.objects.select_related("update_ref")
            .filter(update_ref__diseases_ref__in=disease_ids)
            .exclude(product_code=product_code)
            .distinct()
        )

        if not products.exists():
            return Response({})

        # Prepare similarity
        df = pd.DataFrame(
            [
                {
                    "product_code": p.product_code,
                    "product_title": p.product_title,
                    "summary_of_guidance": p.update_ref.summary_of_guidance
                    if p.update_ref
                    else "",
                    "product_type": p.update_ref.product_type if p.update_ref else "",
                }
                for p in products
            ]
        )

        df["text"] = (
            df["product_title"].fillna("")
            + " "
            + df["summary_of_guidance"].fillna("")
            + " "
            + df["product_type"].fillna("")
        )

        ref_text = (
            product.product_title
            + " "
            + (product_update.summary_of_guidance or "")
            + " "
            + (product_update.product_type or "")
        )
        texts = [ref_text] + df["text"].tolist()

        vectorizer = TfidfVectorizer(stop_words="english")
        tfidf_matrix = vectorizer.fit_transform(texts)
        cosine_sim = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()

        df["similarity_score"] = cosine_sim

        # Filter low similarity
        df = df[df["similarity_score"] > 0.18]

        # Grouped output with 'has_more'
        grouped = {}
        ITEMS_PER_TYPE = 2  # Change to 3 if you prefer

        for product_type, group in df.groupby("product_type"):
            group_sorted = group.sort_values("similarity_score", ascending=False)
            codes = group_sorted["product_code"].tolist()
            top_codes = codes[:ITEMS_PER_TYPE]
            has_more = len(codes) > ITEMS_PER_TYPE
            related_objs = Product.objects.filter(product_code__in=top_codes)
            serializer = RelatedProductSerializer(related_objs, many=True)
            grouped[product_type] = {
                "items": serializer.data,
                "has_more": has_more,
                "total_count": len(codes),
            }

        return Response(grouped)

    # ------------------------------------------------------------------ #
    # NEW: API — fill missing order limits using external_key            #
    # ------------------------------------------------------------------ #
    @action(detail=False, methods=["post"], url_path="fill-missing-order-limits")
    def fill_missing_order_limits(self, request: HttpRequest):
        """
        Back-fill default OrderLimitPage rows for products.

        Optional JSON body:
          {
            "product_codes": ["2023004-Leaflet-English", "..."],  # subset; if omitted, all products
            "dry_run": true                                       # simulate without committing
          }

        Returns per-product orgs created and total count.
        """
        qs = Product.objects.all()
        product_codes = request.data.get("product_codes")
        if product_codes:
            codes = [str(pc).strip() for pc in product_codes if str(pc).strip()]
            qs = qs.filter(product_code__in=codes)

        dry_run = bool(request.data.get("dry_run"))
        total_created = 0
        per_product: Dict[str, List[str]] = {}

        with transaction.atomic():
            for product in qs.iterator():
                created = self.ensure_default_order_limits(product)
                per_product[product.product_code] = created
                total_created += len(created)

            if dry_run:
                transaction.set_rollback(True)

        return Response(
            {
                "message": "Backfill complete.",
                "order_limits_created": total_created,
                "per_product": per_product,
            },
            status=status.HTTP_200_OK,
        )


class PresignedUrlMixin:
    _ALL_SLOTS: tuple[str, ...] = (
        "main_download_url",
        "web_download_url",
        "print_download_url",
        "transcript_url",
        "video_url",
    )

    # -------- URL collection --------
    def _collect_s3_urls(
        self, product_downloads: Dict[str, Any], *, slots: List[str]
    ) -> List[str]:
        def extract_from_val(val: Any) -> List[str]:
            if isinstance(val, dict):
                return [val.get("s3_bucket_url")] if val.get("s3_bucket_url") else []
            if isinstance(val, list):
                return [
                    it.get("s3_bucket_url")
                    for it in val
                    if isinstance(it, dict) and it.get("s3_bucket_url")
                ]
            return []

        urls = []
        for slot in slots:
            urls.extend(extract_from_val(product_downloads.get(slot)))

        # de-dupe while preserving order
        seen, out = set(), []
        for u in urls:
            if u and u not in seen:
                seen.add(u)
                out.append(u)
        return out

    # -------- applicators --------
    @staticmethod
    def _is_doc_mime(m: str) -> bool:
        m = (m or "").lower()
        return any(
            token in m
            for token in (
                "application/pdf",
                "application/msword",
                "application/vnd.openxmlformats-officedocument",
                "application/vnd.oasis.opendocument",
                "application/vnd.ms-powerpoint",
                "application/vnd.ms-excel",
            )
        )

    def _apply_metadata_and_presigned(
        self,
        item: Any,
        presigned: Dict[str, str],
        inline_presigned: Dict[str, str],
        metadata_dict: Dict[str, Dict[str, Any]],
    ) -> Any:
        if isinstance(item, list):
            return [
                self._apply_metadata_and_presigned(
                    i, presigned, inline_presigned, metadata_dict
                )
                for i in item
            ]
        if not isinstance(item, dict) or not item.get("s3_bucket_url"):
            return item

        s3_url = item["s3_bucket_url"]
        item = self._apply_presigned_and_metadata(
            item, s3_url, presigned, metadata_dict
        )
        ip = inline_presigned.get(s3_url)
        if ip:
            item["inline_presigned_s3_url"] = ip
        return item

    def _apply_presigned_and_metadata(
        self,
        item: Dict[str, Any],
        s3_url: str,
        presigned: Dict[str, str],
        metadata_dict: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        presigned_url = presigned.get(s3_url)
        if not presigned_url:
            return item

        item["URL"] = presigned_url
        md = metadata_dict.get(presigned_url, {})
        self._apply_core_metadata(item, md)
        self._apply_optional_metadata(item, md)
        item["s3_bucket_url"] = s3_url
        return item

    def _apply_core_metadata(self, item: Dict[str, Any], md: Dict[str, Any]) -> None:
        if "file_size" in md:
            item["file_size"] = md["file_size"]
        if "file_type" in md:
            item["file_type"] = md["file_type"]

        file_type = (md.get("file_type") or "").lower()
        if file_type.startswith("image/"):
            item.pop("number_of_pages", None)
            item.pop("page_size", None)
            if "dimensions" in md:
                item["dimensions"] = md["dimensions"]
        elif self._is_doc_mime(file_type):
            for k in ("number_of_pages", "page_size"):
                if k in md:
                    item[k] = md[k]

        if "duration" in md:
            item["duration"] = md["duration"]
        if "dimensions" in md and not file_type.startswith("image/"):
            item["dimensions"] = md["dimensions"]

    def _apply_optional_metadata(
        self, item: Dict[str, Any], md: Dict[str, Any]
    ) -> None:
        for k in (
            "number_of_slides",
            "number_of_paragraphs",
            "number_of_sheets",
            "number_of_paragraphs_odt",
        ):
            if k in md:
                item[k] = md[k]

    # -------- main hook --------
    def _process_presigned_urls(self, response_data: Dict[str, Any]) -> None:
        update_refs = response_data.get("update_ref")
        if not isinstance(update_refs, dict):
            return

        product_downloads = self._parse_product_downloads(
            update_refs.get("product_downloads")
        )
        if not isinstance(product_downloads, dict):
            return
        update_refs["product_downloads"] = product_downloads

        all_slots = list(self._ALL_SLOTS)
        urls_all = self._collect_s3_urls(product_downloads, slots=all_slots)
        if not urls_all:
            return

        presigned, inline_presigned = self._generate_presigned_pairs(urls_all)
        metadata_dict = self._build_metadata_dict(presigned, urls_all)

        for slot in all_slots:
            val = product_downloads.get(slot)
            if val is not None:
                product_downloads[slot] = self._apply_metadata_and_presigned(
                    val, presigned, inline_presigned, metadata_dict
                )

    def _parse_product_downloads(self, product_downloads: Any) -> Any:
        if isinstance(product_downloads, str):
            try:
                return json.loads(product_downloads)
            except json.JSONDecodeError:
                return None
        return product_downloads

    def _generate_presigned_pairs(
        self, urls_all: List[str]
    ) -> tuple[Dict[str, str], Dict[str, str]]:
        ttl = getattr(settings, "PRESIGNED_URL_TTL", 3600)
        presigned = generate_presigned_urls(
            urls_all, expiration=ttl, force_download=True
        )
        inline_presigned = generate_presigned_urls(
            urls_all, expiration=ttl, force_download=False
        )
        return presigned, inline_presigned

    def _build_metadata_dict(
        self, presigned: Dict[str, str], urls_all: List[str]
    ) -> Dict[str, Dict[str, Any]]:
        if not getattr(settings, "FILE_METADATA_ENABLED", True):
            return {}

        presigned_urls = [presigned[u] for u in urls_all if u in presigned]
        metas = get_file_metadata(presigned_urls, deep_for_doc_types=True)
        metadata_dict: Dict[str, Dict[str, Any]] = {}
        for m in metas:
            if not isinstance(m, dict) or not m.get("URL"):
                continue
            metadata_dict[m["URL"]] = {
                k: m[k]
                for k in m
                if k
                in (
                    "file_size",
                    "file_type",
                    "number_of_pages",
                    "page_size",
                    "duration",
                    "dimensions",
                    "number_of_slides",
                    "number_of_paragraphs",
                    "number_of_sheets",
                    "number_of_paragraphs_odt",
                )
            }
        return metadata_dict


# --------------------------------------------------------------------------- #
# Product detail view
# --------------------------------------------------------------------------- #
class ProductDetailView(PresignedUrlMixin, viewsets.ViewSet):
    """
    Retrieves a single Product by its product_code.
    Includes presigned S3 URLs, order limit prefetch, and caching.
    """

    authentication_classes = [CustomTokenAuthentication, SessionAuthentication]
    permission_classes = [AllowAny]

    def retrieve(self, request, product_code=None, *args, **kwargs):
        # Decode and sanitize product code
        code = unquote(product_code or "").strip()
        if not code:
            return handle_error(
                ErrorCode.PRODUCT_NOT_FOUND,
                ErrorMessage.PRODUCT_NOT_FOUND,
                status.HTTP_404_NOT_FOUND,
            )

        #  Prefetch related order_limits for per-user org limit lookups
        product = (
            Product.objects.filter(product_code=code)
            .select_related("update_ref")
            .prefetch_related("order_limits")
            .first()
        )

        if not product:
            return handle_error(
                ErrorCode.PRODUCT_NOT_FOUND,
                ErrorMessage.PRODUCT_NOT_FOUND,
                status.HTTP_404_NOT_FOUND,
            )

        # Build version timestamp for cache key
        ver_ts = self._get_version_timestamp(product)
        cache_key, bypass_cache = self._get_cache_key_and_bypass(request, code, ver_ts)

        # Try returning cached response (skip for staff or ?fresh=1)
        if not bypass_cache:
            cached_data = cache.get(cache_key)
            if cached_data:
                return self._cached_response(cached_data, code, ver_ts)

        #  Serialize product with full context (for user-aware fields)
        serializer = ProductSerializer(product, context={"request": request})
        data = serializer.data

        #  Apply presigned URLs and metadata
        self._process_presigned_urls(data)

        #  Cache the result for faster repeated lookups
        ttl = getattr(settings, "CACHE_TTL_DETAIL", 60)
        if ttl > 0 and not bypass_cache:
            cache.set(cache_key, data, ttl)

        #  Return the fresh JSON response
        return self._fresh_response(data, code, ver_ts)

    # ------------------------------
    # Internal helpers
    # ------------------------------

    def _get_version_timestamp(self, product: Product) -> int:
        """Build a version-based timestamp using product + update_ref."""
        timestamps = []
        if getattr(product, "updated_at", None):
            timestamps.append(product.updated_at)
        if getattr(product, "update_ref", None) and getattr(
            product.update_ref, "updated_at", None
        ):
            timestamps.append(product.update_ref.updated_at)
        return int(max(timestamps).timestamp()) if timestamps else 0

    def _get_cache_key_and_bypass(
        self, request, code: str, ver_ts: int
    ) -> tuple[str, bool]:
        """Compose cache key and determine whether to skip cache."""
        cache_key = f"product_detail:v{ver_ts}:{code}"
        bypass_cache = (request.GET.get("fresh") == "1") or getattr(
            request.user, "is_staff", False
        )
        return cache_key, bypass_cache

    def _cached_response(self, cached: dict, code: str, ver_ts: int) -> JsonResponse:
        """Return cached JSON response with headers."""
        resp = JsonResponse(cached, status=status.HTTP_200_OK)
        self._set_headers(resp, code, ver_ts)
        return resp

    def _fresh_response(self, data: dict, code: str, ver_ts: int) -> JsonResponse:
        """Return new JSON response with proper headers."""
        resp = JsonResponse(data, status=status.HTTP_200_OK)
        self._set_headers(resp, code, ver_ts)
        return resp

    def _set_headers(self, resp: JsonResponse, code: str, ver_ts: int) -> None:
        """Attach cache + version headers for client-side consistency."""
        resp["Cache-Control"] = "no-store"
        resp["ETag"] = f'W/"{code}-{ver_ts}"'
        if ver_ts:
            resp["Last-Modified"] = http_date(ver_ts)


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
        editor = getattr(request, "user", None)
        if isinstance(editor, User):
            product.user_ref = editor
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


class ProductStatusUpdateView(APIView):
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

            editor = getattr(request, "user", None)
            if isinstance(editor, User):
                product.user_ref = editor
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
            invalidate_product_caches(product.product_code)

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


class ProductUpdateView(APIView):
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
            editor = getattr(request, "user", None)
            if isinstance(editor, User):
                product.user_ref = editor

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

        # ----------------- ATOMIC: ProductUpdate + Product ------------------ #
        with transaction.atomic():
            logger.info(
                "Starting atomic transaction for product_code=%s", decoded_product_code
            )

            # Ensure/update ProductUpdate
            product_update = self.get_or_create_product_update(
                product, product_update_data
            )
            logger.info(
                "ProductUpdate ensured for product_code=%s (id=%s)",
                decoded_product_code,
                product_update.id,
            )
            #  Set last-updated-by before saving
            editor = getattr(request, "user", None)
            if isinstance(editor, User):
                product.user_ref = editor

            # Update foreign keys
            self.update_foreign_keys(product_update, data)
            logger.debug(
                "Updated foreign keys on ProductUpdate id=%s", product_update.id
            )

            # Patch Product itself
            serializer = ProductSerializer(
                product, data=data, partial=True, context={"request": request}
            )
            if not serializer.is_valid():
                logger.error(
                    "Validation errors for product_code=%s: %s",
                    decoded_product_code,
                    serializer.errors,
                )
                return handle_error(
                    ErrorCode.INVALID_DATA, ErrorMessage.INVALID_DATA, status_code=400
                )
            serializer.save()
            logger.info(
                "Product patched successfully for product_code=%s", decoded_product_code
            )

        # --------------- OUTSIDE ATOMIC: Order limits ------------------------ #
        if data.get("order_limits"):
            logger.info(
                "Processing order_limits for product_code=%s", decoded_product_code
            )
            try:
                self.update_order_limits(product, data["order_limits"])
                logger.info(
                    "Order limits updated for product_code=%s", decoded_product_code
                )
            except Exception as e:
                logger.exception(
                    "Order limits update failed for product_code=%s: %s",
                    decoded_product_code,
                    e,
                )

        # Build response
        response_data = ProductSerializer(product, context={"request": request}).data
        response_data["update_ref"] = ProductUpdateSerializer(
            product.update_ref, context={"request": request}
        ).data

        logger.info(
            "PATCH request completed successfully for product_code=%s",
            decoded_product_code,
        )
        invalidate_product_caches(product.product_code)
        return JsonResponse(response_data, status=status.HTTP_200_OK)

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
        logger.debug(
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
        """
        Attach presigned URLs and file metadata to file_urls.
        Ensures TTL alignment with cache and safe defaults if metadata is missing.
        """
        presign_ttl = int(getattr(settings, "PRESIGNED_URL_TTL", 3600))
        effective_ttl = max(0, presign_ttl - 5)  # safety margin

        # Collect URLs
        all_urls = []
        if file_urls.get("main_download_url"):
            all_urls.append(file_urls["main_download_url"])
        for key, value in file_urls.items():
            if key != "main_download_url" and isinstance(value, list):
                all_urls.extend(value)

        # Generate presigns
        presigned = generate_presigned_urls(all_urls, expiration=effective_ttl)
        inline_presigned = generate_inline_presigned_urls(
            all_urls, expiration=effective_ttl
        )

        # Metadata lookup (guarded by feature flag if needed)
        metadata_dict = {}
        if getattr(settings, "FILE_METADATA_ENABLED", True) and presigned:
            metadata_list = get_file_metadata(list(presigned.values()))
            metadata_dict = {meta["URL"]: meta for meta in metadata_list}

        # Build a new dict (don’t mutate in place)
        result = {}
        for key, value in file_urls.items():
            if key == "main_download_url" and value:
                presigned_url = presigned.get(value)
                meta = metadata_dict.get(presigned_url, {"URL": value})
                result[key] = {
                    **meta,
                    "s3_bucket_url": value,
                    "inline_presigned_s3_url": inline_presigned.get(value, ""),
                }
            elif isinstance(value, list):
                result[key] = [
                    {
                        **metadata_dict.get(presigned.get(url), {"URL": url}),
                        "s3_bucket_url": url,
                        "inline_presigned_s3_url": inline_presigned.get(url, ""),
                    }
                    for url in value
                ]
            else:
                result[key] = value

        return result

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
        Upserts OrderLimitPage records for each organisation with latest order_limit
        and full_external_keys derived from Establishment records.
        Ensures there is only ONE record per organisation.
        """
        try:
            parent_page = Page.objects.get(slug="products")
        except Page.DoesNotExist:
            logger.error("Parent page with slug 'products' not found.")
            return

        # Existing pages grouped by org name
        existing_pages = (
            OrderLimitPage.objects.child_of(parent_page)
            .filter(product_ref=product)
            .select_related("organization_ref")
        )
        by_org = {p.organization_ref.name: p for p in existing_pages}

        # Prefetch org + establishment data
        org_names = [
            lim["organization_name"]
            for lim in order_limits
            if lim.get("organization_name")
        ]

        if not org_names:
            # If no limits supplied, delete all existing for this product
            for page in existing_pages:
                page.delete()
            return

        org_qs = Organization.objects.filter(name__in=org_names)
        org_cache = {org.name: org for org in org_qs}

        est_qs = Establishment.objects.filter(organization_ref__in=org_qs).values(
            "organization_ref_id", "full_external_key"
        )
        full_keys_map = defaultdict(list)
        for est in est_qs:
            full_keys_map[est["organization_ref_id"]].append(est["full_external_key"])

        # --- Upsert loop ---
        seen_orgs = set()
        for lim in order_limits:
            org_name = lim.get("organization_name")
            if not org_name:
                continue

            org = org_cache.get(org_name)
            if not org:
                logger.warning("Organization '%s' not found. Skipping.", org_name)
                continue

            seen_orgs.add(org_name)
            limit_val = lim.get("order_limit_value", 0)
            full_keys = full_keys_map.get(org.organization_id, [])

            page = by_org.get(org_name)
            if page:
                # Only publish if something actually changed
                if (
                    page.order_limit != limit_val
                    or page.full_external_keys != full_keys
                ):
                    page.order_limit = limit_val
                    page.full_external_keys = full_keys
                    page.save_revision().publish()
                continue

            # Otherwise create a new one
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

        # --- Delete any obsolete ones (not in current payload) ---
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
        auth_user = getattr(request, "user", None)
        if isinstance(auth_user, User):
            user_instance = auth_user
        else:
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
        invalidate_product_caches(product_instance.product_code)
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
        # remove hyphens (and any other non-alphanumerics) from the ISO code:
        clean_lang = re.sub(r"[^A-Za-z0-9]", "", iso_language_code)
        short_language_code = clean_lang[:4]
        product_code = f"{short_program_id}{short_product_key}{short_language_code}{version_number:03}"
        while Product.objects.filter(product_code=product_code).exists():
            version_number += 1
            product_code = f"{short_program_id}{short_product_key}{short_language_code}{version_number:03}"
        logger.debug("Unique product code: %s", product_code)
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


# --------------------------------------------------------------------------- #
# Core mixin with sorting + normalization/dedupe + list caching               #


# ----------------------------- fallbacks -------------------------------------

if "ALLOWED_SORT_FIELDS" not in globals():
    ALLOWED_SORT_FIELDS = {
        "product_title",
        "-product_title",
        "created_at",
        "-created_at",
        "publish_date",
        "-publish_date",
        "updated_at",
        "-updated_at",
        "program_id",
        "-program_id",
    }

if "VALID_SORT_FIELDS" not in globals():
    VALID_SORT_FIELDS = list(ALLOWED_SORT_FIELDS)

# A conservative pattern; keep your original if already defined elsewhere.
if "PRODUCT_CODE_PATTERN" not in globals():
    PRODUCT_CODE_PATTERN = r"^[A-Za-z0-9\-_]+$"


# --------------------------------------------------------------------------- #
# Core mixin: sorting + normalization/dedupe + pagination/presign/cache       #
# --------------------------------------------------------------------------- #


class ProductListMixin:
    """
    Shared logic for all product list endpoints (admin/user/search/filter).
    Handles:
      - norm-code annotation
      - dedupe
      - sorting
      - caching
      - pagination
      - presigned URLs (users only)
    """

    serializer_class = ProductSerializer
    search_serializer_class = ProductSearchSerializer
    include_request_context = False

    cache_timeout = getattr(settings, "CACHE_TTL_LIST", 30)
    pagination_class = CustomPagination

    # Default: presign for user-facing views
    presign_in_lists = getattr(settings, "PRESIGN_IN_LISTS", True)

    # ---------------------------------------------------------------------- #
    # FAST NORM-CODE ANNOTATION (Cached)
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _norm_annotations():
        norm_expr = Upper(
            Replace(
                Replace(
                    Replace(Trim(F("product_code")), Value("-"), Value("")),
                    Value("_"),
                    Value(""),
                ),
                Value(" "),
                Value(""),
            )
        )

        return {
            "code_trim": Trim(F("product_code")),
            "norm_code": norm_expr,
        }

    def _annotate_norm_code(self, qs):
        cache_key = f"annotate_norm:{hash(qs.query)}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        annotated = qs.annotate(**self._norm_annotations())
        cache.set(cache_key, annotated, 300)
        return annotated

    def _exclude_edge_spaces(self, qs):
        """
        Keep only rows whose product_code equals its trimmed version (no leading/trailing spaces).
        """
        return qs.filter(product_code=F("code_trim"))

    # ---------------------------------------------------------------------- #
    # SEARCH OPTIMIZATION (User-facing lists)
    # ---------------------------------------------------------------------- #

    def optimize_for_search(self, qs):
        """
        Lightweight preparation for user-facing lists.
        Does NOT change admin queryset behavior.
        """
        qs = self._annotate_norm_code(qs)
        qs = qs.filter(product_code=F("code_trim"))

        return qs.select_related(
            "program_id",
            "language_id",
            "update_ref",
        )

    # ---------------------------------------------------------------------- #
    # SORTING
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _model_has_field(model, name: str) -> bool:
        try:
            model._meta.get_field(name)
            return True
        except Exception:
            return False

    def _best_updated_field(self, qs):
        for name in (
            "updated_at",
            "latest_revision_created_at",
            "last_published_at",
            "first_published_at",
            "created_at",
            "publish_date",
        ):
            if self._model_has_field(qs.model, name):
                return name
        return None

    def _normalize_sort_param(self, sort_by):
        if not sort_by:
            return None
        return sort_by if sort_by in ALLOWED_SORT_FIELDS else None

    def _resolve_sort_field(self, qs, field):
        sign = "-" if field.startswith("-") else ""
        raw = field.lstrip("-")

        # 1) Explicit publish_date should *stay* publish_date
        if raw == "publish_date":
            if self._model_has_field(qs.model, "publish_date"):
                return f"{sign}publish_date"
            # If model doesn't have publish_date, fall back safely
            return f"{sign}id"

        # 2) For updated_at / created_at, pick the "best" available date field
        if raw in {"updated_at", "created_at"}:
            best = self._best_updated_field(qs)
            return f"{sign}{best}" if best else f"{sign}id"

        # 3) All other fields: honour exactly if they exist, else fall back to id
        return f"{sign}{raw}" if self._model_has_field(qs.model, raw) else f"{sign}id"

    def get_sorted_queryset(self, qs, request):
        req = self._normalize_sort_param(request.GET.get("sort_by"))
        if req:
            resolved = self._resolve_sort_field(qs, req)
            is_desc = resolved.startswith("-")
            return qs.order_by(resolved, "-id" if not is_desc else "id")

        # Default sorting
        best = self._best_updated_field(qs)
        primary = f"-{best}" if best else "-id"
        return qs.order_by(primary, "id" if primary.startswith("-") else "-id")

    # ---------------------------------------------------------------------- #
    # DEDUPE (FAST + Cached)
    # ---------------------------------------------------------------------- #

    def _dedupe_by_norm_code_fast(self, qs):
        cache_key = f"dedupe_fast:{hash(qs.query)}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        q = self._annotate_norm_code(qs).filter(product_code=F("code_trim"))
        updated_field = self._best_updated_field(q) or "id"

        best_row = (
            q.filter(norm_code=OuterRef("norm_code"))
            .order_by(F(updated_field).desc(nulls_last=True), F("id").desc())
            .values("id")[:1]
        )

        best_ids = (
            q.values("norm_code").annotate(best_id=Subquery(best_row)).values("best_id")
        )

        result = Product.objects.filter(id__in=Subquery(best_ids))
        cache.set(cache_key, result, 300)
        return result

    # ---------------------------------------------------------------------- #
    # CACHE KEYS
    # ---------------------------------------------------------------------- #

    def _normalized_path_for_cache(self, request):
        parts = urlsplit(request.get_full_path())
        pairs = parse_qsl(parts.query, keep_blank_values=True)

        def keep(k):
            kl = k.lower()
            if kl in {"requesttime", "_", "cachebust", "fresh"}:
                return False
            if kl.startswith("utm_"):
                return False
            return True

        cleaned = [(k, v) for (k, v) in pairs if keep(k)]
        cleaned.sort()
        q = urlencode(cleaned, doseq=True)
        return parts.path + (("?" + q) if q else "")

    def get_cache_key(self, request, prefix="products"):
        user_id = getattr(request.user, "id", "anon")
        path = self._normalized_path_for_cache(request)
        return f"{prefix}:user:{user_id}:{path}"

    # ---------------------------------------------------------------------- #
    # PAGINATION + SERIALIZATION + PRESIGN
    # ---------------------------------------------------------------------- #

    def paginate_and_serialize(
        self,
        qs,
        request,
        serializer_class=None,
        *,
        use_direct_update=False,
        is_search=False,
    ):
        bypass = (self.cache_timeout or 0) <= 0 or request.GET.get("fresh") == "1"

        version = self._queryset_version(qs)
        base_key = self.get_cache_key(request)
        cache_key = f"{base_key}:v{version}"

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)

        if not bypass:
            cached = cache.get(cache_key)
            if cached:
                return cached, paginator

        ctx = {"request": request} if self.include_request_context else {}

        s_class = serializer_class or (
            self.search_serializer_class if is_search else self.serializer_class
        )
        serializer = s_class(page, many=True, context=ctx)
        data = serializer.data

        # USER LISTS ONLY — PRESIGN
        if self.presign_in_lists:
            presign_ttl = int(getattr(settings, "PRESIGNED_URL_TTL", 3600))
            urls = extract_s3_urls(data)
            presigned = generate_presigned_urls(urls, expiration=presign_ttl)
            update_product_urls(data, presigned)

            cache.set(cache_key, data, timeout=min(self.cache_timeout, presign_ttl - 5))
        else:
            cache.set(cache_key, data, timeout=self.cache_timeout)

        return data, paginator

    # ---------------------------------------------------------------------- #
    # QUERYSET VERSIONING
    # ---------------------------------------------------------------------- #

    @staticmethod
    def _to_aware_datetime(value: Any) -> Optional[datetime.datetime]:
        """
        Normalise a value that may be a date or datetime into an aware datetime.
        Returns None if it can't be interpreted.
        """
        if value is None:
            return None

        # DateField (e.g. publish_date) → midnight that day
        if isinstance(value, datetime.date) and not isinstance(
            value, datetime.datetime
        ):
            dt = datetime.datetime.combine(value, datetime.time.min)
        elif isinstance(value, datetime.datetime):
            dt = value
        else:
            return None

        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_default_timezone())
        return dt

    def _queryset_version(self, qs):
        def safe_max(qs, field):
            try:
                return qs.aggregate(mx=Max(field))["mx"]
            except Exception:
                return None

        # Collect raw maxima (may be date or datetime or None)
        raw_candidates = []
        for f in (
            "updated_at",
            "latest_revision_created_at",
            "last_published_at",
            "first_published_at",
            "created_at",
            "publish_date",
        ):
            raw_candidates.append(safe_max(qs, f))

        # Coerce to aware datetimes and drop anything we can't parse
        dt_candidates = [
            self._to_aware_datetime(x) for x in raw_candidates if x is not None
        ]
        dt_candidates = [x for x in dt_candidates if x is not None]

        if not dt_candidates:
            return 0

        d = max(dt_candidates)
        return int(d.timestamp())


class BaseAdminProductsView(ProductListMixin, APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAdminUser]
    include_request_context = True
    presign_in_lists = False
    pagination_class = AdminPagination

    APPLY_FILTERS = False

    def get(self, request, *args, **kwargs):
        PRE_LIST_LIMIT = int(getattr(settings, "ADMIN_PRE_LIST_LIMIT", 1500))

        qs = build_admin_queryset(
            request, apply_filters=self.APPLY_FILTERS
        ).select_related("program_id", "language_id", "update_ref", "user_ref")

        # Sort BEFORE slicing
        qs = self.get_sorted_queryset(qs, request)

        # Slice after ordering
        qs = qs[:PRE_LIST_LIMIT]

        # Cache
        admin_cache_key = (
            f"admin_list:{request.get_full_path()}:v{self._queryset_version(qs)}"
        )
        cached = cache.get(admin_cache_key)
        if cached:
            return Response(cached)

        # Pagination & serialization
        data, paginator = self.paginate_and_serialize(
            qs, request, serializer_class=AdminProductSerializer, is_search=False
        )
        response = paginator.get_paginated_response(data)

        cache.set(admin_cache_key, response.data, 30)
        return response

    # ------------------------------------------------------------------ #
    # Default ordering by updated_at desc                                #
    # ------------------------------------------------------------------ #
    def get_sorted_queryset(self, qs, request):
        """
        Apply sorting based on request params (if provided),
        otherwise default to most recently updated first.
        """
        sort_field = request.query_params.get("sort_by")
        sort_order = request.query_params.get("order", "desc")

        if sort_field:
            # normalize
            sort_field = sort_field.lstrip("-")  # <--- fix
            prefix = "" if sort_order == "asc" else "-"
            return qs.order_by(f"{prefix}{sort_field}")

        # Default ordering
        return qs.order_by("-updated_at")


# --------------------------------------------------------------------------- #
# Admin: List with filters                                                  #
# --------------------------------------------------------------------------- #
class ProductAdminListView(BaseAdminProductsView):
    APPLY_FILTERS = False


# --------------------------------------------------------------------------- #
# Users: List                                                                 #
# --------------------------------------------------------------------------- #
class ProductUsersListView(ProductListMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    include_request_context = True
    presign_in_lists = True  # ❗ USERS NEED PRESIGNED URLS
    cache_timeout = getattr(settings, "CACHE_TTL_LIST", 30)

    def get(self, request, *args, **kwargs):
        try:
            base = Product.objects.filter(is_latest=True, status="live")
            if not base.exists():
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            qs = self.optimize_for_search(base)
            sorted_qs = self.get_sorted_queryset(qs, request)

            data, paginator = self.paginate_and_serialize(
                sorted_qs,
                request,
                serializer_class=ProductSearchSerializer,
                is_search=False,
            )

            data = filter_live_languages(data)
            return paginator.get_paginated_response(data)

        except Exception as e:
            logger.exception("Users list error: %s", e)
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# --------------------------------------------------------------------------- #
# Base search (supplies helpers used by user search)                       #
# --------------------------------------------------------------------------- #


class BaseProductSearchView(APIView, ProductListMixin):
    """Shared helpers for product search views (user/admin/etc.)."""

    pagination_class = CustomPagination

    @staticmethod
    def _normalize_term(term: str) -> str:
        """Normalize search term by uppercasing and removing '-', '_' and spaces."""
        return re.sub(r"[-_\s]+", "", (term or "")).upper()

    @staticmethod
    def _annotate_rank_signals(qs, q: str, q_norm: str, looks_like_code: int):
        """
        Annotate queryset with ranking signals and compute a composite 'rank'.
        This boosts results that exactly or partially match code/title/norm_code.
        """
        return qs.annotate(
            exact_code=Case(
                When(product_code__iexact=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            starts_code=Case(
                When(product_code__istartswith=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            contains_code=Case(
                When(product_code__icontains=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            exact_norm=Case(
                When(norm_code__exact=q_norm, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            starts_norm=Case(
                When(norm_code__startswith=q_norm, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            contains_norm=Case(
                When(norm_code__contains=q_norm, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            exact_title=Case(
                When(product_title__iexact=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            starts_title=Case(
                When(product_title__istartswith=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            contains_title=Case(
                When(product_title__icontains=q, then=Value(1)),
                default=Value(0),
                output_field=IntegerField(),
            ),
            code_bias=Value(looks_like_code, output_field=IntegerField()),
        ).annotate(
            rank=(
                120 * F("exact_norm")
                + 95 * F("starts_norm")
                + 75 * F("contains_norm")
                + 100 * F("exact_code")
                + 80 * F("starts_code")
                + 60 * F("contains_code")
                + 70 * F("exact_title")
                + 50 * F("starts_title")
                + 30 * F("contains_title")
                + 10 * F("code_bias")
            )
        )


# --------------------------------------------------------------------------- #
# Users: Public search endpoint                                               #
# --------------------------------------------------------------------------- #
class ProductSearchUserView(BaseProductSearchView):
    """
    GET /api/v1/products/users/search/?q=...&page=1
    Public search, optimized for UI needs.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    include_request_context = True
    cache_timeout = getattr(settings, "CACHE_TTL_LIST", 30)
    pagination_class = CustomPagination

    # tuneable cap for the pre-ranked set (before dedupe/rank)
    PRE_RANK_LIMIT = int(getattr(settings, "SEARCH_PRE_RANK_LIMIT", 2000))

    def get(self, request, *args, **kwargs) -> Response:
        try:
            q = (request.GET.get("q") or "").strip()
            base = Product.objects.filter(is_latest=True, status="live")

            # Case 1: Empty query → dedupe + default sort
            if not q:
                deduped = self._dedupe_by_norm_code_fast(base)
                deduped = self.get_sorted_queryset(
                    deduped.select_related("update_ref"), request
                )
                data, paginator = self.paginate_and_serialize(
                    deduped,
                    request,
                    serializer_class=ProductSearchSerializer,
                    is_search=True,
                )
                data = filter_live_languages(data)
                return paginator.get_paginated_response(data)

            # Case 2: Search with query
            q_norm = self._normalize_term(q)
            looks_like_code = 1 if re.fullmatch(r"[A-Za-z0-9_-]+", q) else 0

            restricted = base.filter(
                Q(product_code__icontains=q) | Q(product_title__icontains=q)
            )
            restricted = self._annotate_norm_code(restricted).filter(
                Q(norm_code__icontains=q_norm)
                | Q(product_code__icontains=q)
                | Q(product_title__icontains=q)
            )

            updated_field = self._best_updated_field(restricted) or "id"
            # Slice safely → extract IDs first
            restricted_ids = list(
                restricted.order_by(
                    F(updated_field).desc(nulls_last=True), "-id"
                ).values_list("id", flat=True)[: self.PRE_RANK_LIMIT]
            )

            # Rebuild a non-sliced queryset
            restricted_qs = Product.objects.filter(id__in=restricted_ids)

            # Now dedupe is safe
            deduped = self._dedupe_by_norm_code_fast(restricted_qs)

            ranked = self._annotate_norm_code(deduped)
            ranked = self._annotate_rank_signals(ranked, q, q_norm, looks_like_code)

            sort_by = self._normalize_sort_param(request.GET.get("sort_by"))
            if sort_by:
                ranked = ranked.order_by("-rank", sort_by, "-id")
            else:
                updated_desc = self._resolve_sort_field(ranked, "-updated_at") or "-id"
                ranked = ranked.order_by("-rank", "product_title", updated_desc, "-id")

            ranked = ranked.select_related("update_ref")

            data, paginator = self.paginate_and_serialize(
                ranked,
                request,
                serializer_class=ProductSearchSerializer,
                is_search=True,
            )
            data = filter_live_languages(data)
            return paginator.get_paginated_response(data)

        except Exception:
            logger.exception("User search error")
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# --------------------------------------------------------------------------- #
# Admin: Search endpoint                                                      #
# --------------------------------------------------------------------------- #
class ProductSearchAdminView(BaseProductSearchView):
    """
    Admin-only search view.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get_default_query(self) -> Q:
        return Q()


# --------------------------------------------------------------------------- #
# Users: Faceted Filter                                                       #
# --------------------------------------------------------------------------- #
class ProductUsersFilterView(ProductListMixin, APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    include_request_context = True
    pagination_class = CustomPagination
    cache_timeout = getattr(settings, "CACHE_TTL_LIST", 30)

    def get(self, request, *args, **kwargs):
        try:
            base_q = Q(is_latest=True, status="live")
            filters = Q()

            # Access type (normalize to hyphenated tags)
            if request.GET.get("download_only", "").lower() == "true":
                filters &= Q(tag="download-only")
            elif request.GET.get("download_or_order", "").lower() == "true":
                filters &= Q(tag="download-or-order")
            elif request.GET.get("order_only", "").lower() == "true":
                filters &= Q(tag="order-only")

            mapping = [
                ("audiences", "update_ref__audience_ref__name"),
                ("diseases", "update_ref__diseases_ref__name"),
                ("vaccinations", "update_ref__vaccination_ref__name"),
                ("program_names", "program_name"),
                ("program_ids", "program_id"),
                ("where_to_use", "update_ref__where_to_use_ref__name"),
                ("alternative_type", "update_ref__alternative_type"),
                ("product_type", "update_ref__product_type"),
                ("languages", "language_name"),
            ]
            for param, lookup in mapping:
                vals = request.GET.getlist(param)
                if vals:
                    filters &= Q(**{f"{lookup}__in": vals})

            qs = Product.objects.filter(base_q & filters)
            qs = self._dedupe_by_norm_code_fast(qs)
            qs = self.optimize_for_search(qs)
            qs = self.get_sorted_queryset(qs, request)

            data, paginator = self.paginate_and_serialize(
                qs,
                request,
                serializer_class=ProductSearchSerializer,
                is_search=True,
            )
            data = filter_live_languages(data)
            return paginator.get_paginated_response(data)
        except Exception:
            logger.exception("User filter error")
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# --------------------------------------------------------------------------- #
# Admin: Faceted Filter                                                       #
# --------------------------------------------------------------------------- #


class ProductAdminFilterView(BaseAdminProductsView):
    """Admin list with faceted filters applied."""

    APPLY_FILTERS = True


# --------------------------------------------------------------------------- #
# Users: Search + Filter (DjangoFilter + SearchFilter)                        #
# --------------------------------------------------------------------------- #


class ProductUsersSearchFilterAPIView(generics.ListAPIView, ProductListMixin):
    """
    GET /api/v1/products/user/search/filter/
      Supports:
        - ?search= (search in product_title, product_code_no_dashes)
        - Faceted filters via ProductFilter
        - ?sort_by= (uniform custom sorting)
      Always presigns images/downloads for user-facing results.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    serializer_class = ProductSearchSerializer
    pagination_class = CustomPagination

    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_class = ProductFilter
    search_fields = ["product_title", "product_code_no_dashes"]

    ordering_fields = list(
        dict.fromkeys([*VALID_SORT_FIELDS, "norm_code", "-norm_code"])
    )
    ordering = ["product_title", "-updated_at"]

    def get_queryset(self):
        base = Product.objects.filter(status="live", is_latest=True)
        base = self._annotate_norm_code(base)
        base = self._exclude_edge_spaces(base)
        base = self._dedupe_by_norm_code(base)
        return self.optimize_for_search(base)

    def _dedupe_by_norm_code(self, qs):
        return self._dedupe_by_norm_code_fast(qs)

    def list(self, request, *args, **kwargs):
        try:
            qs = self.filter_queryset(self.get_queryset())
            qs = self.get_sorted_queryset(qs, request)

            data, paginator = self.paginate_and_serialize(
                qs,
                request,
                serializer_class=ProductSearchSerializer,
                is_search=True,  #  ensures presign for user-facing
            )
            data = filter_live_languages(data)
            return paginator.get_paginated_response(data)

        except Exception:
            logger.exception("User search+filter error")
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


# --------------------------------------------------------------------------- #
# Program-scoped: Products (with optional facets)                             #
# --------------------------------------------------------------------------- #
class ProgramProductsView(ProductListMixin, generics.ListAPIView):
    """
    GET /api/v1/programmes/<program_id>/products/
    Supports:
      - program scoping (diseases/vaccinations tied to program)
      - optional facets (same as user filter)
      - uniform ?sort_by=
      - cache key versioned by latest updated_at (auto-refresh on data change)
    """

    serializer_class = ProductSerializer
    pagination_class = CustomPagination
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    cache_timeout = settings.CACHE_TTL_LIST

    def get_cache_key(self, request, program_id):
        """
        Generate a deterministic, cache-safe key.
        Uses SHA-256 (secure, no collision risk).
        """
        user_id = (
            request.user.id
            if getattr(request, "user", None) and request.user.is_authenticated
            else "anon"
        )

        full_path = request.get_full_path().encode("utf-8")
        path_hash = hashlib.sha256(full_path).hexdigest()
        return f"prog_products:{program_id}:user:{user_id}:{path_hash}"

    def _build_facets(self, request) -> Q:
        q = Q()
        for param, lookup in [
            ("audiences", "update_ref__audience_ref__name__in"),
            ("diseases", "update_ref__diseases_ref__name__in"),
            ("vaccinations", "update_ref__vaccination_ref__name__in"),
            ("where_to_use", "update_ref__where_to_use_ref__name__in"),
            ("alternative_type", "update_ref__alternative_type__in"),
            ("product_type", "update_ref__product_type__in"),
            ("languages", "language_name__in"),
            ("access_type", "tag__in"),
        ]:
            vals = request.GET.getlist(param)
            if vals:
                q &= Q(**{lookup: vals})
        return q

    def get_queryset(self):
        program = get_object_or_404(Program, pk=self.kwargs["program_id"])
        diseases = Disease.objects.filter(programs=program)
        vaccinations = Vaccination.objects.filter(programs=program)

        # Base scope: live + latest
        qs = (
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
        )

        # Apply optional facets
        facet_q = self._build_facets(self.request)
        if facet_q:
            qs = qs.filter(facet_q)

        return self._dedupe_by_norm_code_fast(qs)

    # -------------------- Main List --------------------

    def list(self, request, *args, **kwargs):
        program_id = kwargs["program_id"]

        # Build queryset (used for both data + versioning)
        qs = self.get_queryset()
        qs = self.get_sorted_queryset(qs, request)

        # Compute cache key with version suffix (based on updated_at freshness)
        base_key = self.get_cache_key(request, program_id)
        version = self._queryset_version(qs)  # from ProductListMixin
        cache_key = f"{base_key}:v{version}"

        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        # Paginate + serialize
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(
                page, many=True, context=self.get_serializer_context()
            )

            # Generate presigned URLs for attachments
            all_urls = extract_s3_urls(serializer.data)
            presigned = generate_presigned_urls(all_urls)
            update_product_urls(serializer.data, presigned)

            response = self.get_paginated_response(serializer.data)

            # Add related program context
            program = get_object_or_404(Program, pk=program_id)
            response.data["diseases"] = DiseaseSerializer(
                Disease.objects.filter(programs=program), many=True
            ).data
            response.data["vaccinations"] = VaccinationSerializer(
                Vaccination.objects.filter(programs=program), many=True
            ).data

            cache.set(cache_key, response.data, self.cache_timeout)
            return response

        # Non-paginated fallback (rare)
        serializer = self.get_serializer(
            qs, many=True, context=self.get_serializer_context()
        )
        data = serializer.data
        all_urls = extract_s3_urls(data)
        presigned = generate_presigned_urls(all_urls)
        update_product_urls(data, presigned)

        program = get_object_or_404(Program, pk=program_id)
        payload = {
            "results": data,
            "diseases": DiseaseSerializer(
                Disease.objects.filter(programs=program), many=True
            ).data,
            "vaccinations": VaccinationSerializer(
                Vaccination.objects.filter(programs=program), many=True
            ).data,
        }

        cache.set(cache_key, payload, self.cache_timeout)
        return Response(payload, status=status.HTTP_200_OK)


# --------------------------------------------------------------------------- #
# Misc: Incomplete drafts warning                                             #
# --------------------------------------------------------------------------- #
class IncompleteProductsView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

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


#
