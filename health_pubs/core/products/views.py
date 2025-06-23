import datetime
import json
import logging
import re
import uuid
from typing import Optional, Union
from urllib.parse import unquote
from django.utils import timezone
from datetime import timedelta
import time
from django.db import IntegrityError
from psycopg2 import errors as pg_errors

import pandas as pd
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
from rest_framework.generics import ListAPIView
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
from django.core.exceptions import ObjectDoesNotExist, ValidationError
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

from .models import Product, ProductUpdate
from .serializers import (
    ProductSearchSerializer,
    ProductSerializer,
    ProductUpdateSerializer,
)
from rest_framework.generics import ListAPIView
from django.core.serializers.json import DjangoJSONEncoder

from configs.get_secret_config import Config


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
    """
    Common helper methods for creating/updating products in bulk.
    """

    def skip_row(self, index, message):
        logger.warning(f"Skipping row {index + 1}: {message}")
        return {"skipped": True, "error": {"row": index + 1, "error": message}}

    def safe_add_child(self, parent, instance):
        parent.add_child(instance=instance)
        return instance

    def clean_row_data(self, row):
        row["run_to_zero"] = self._clean_run_to_zero(row.get("run_to_zero"))
        row = self._clean_invalid_strings(row)
        # normalize the available_until_choice field
        row["available_until_choice"] = self._clean_available_until_choice(
            row.get("available_until_choice")
        )
        for key in ("local_code", "cost_centre"):  # remove numeric fallback
            val = row.get(key)
            if isinstance(val, (int, float)) or (
                isinstance(val, str) and val.replace(".", "", 1).isdigit()
            ):
                row[key] = None

        for key in [
            "unit_of_measure",
            "programme_id",
            "language_id",
            "audience_id",
            "where_to_use_id",
            "vaccination_id",
            "disease_id",
            "minimum_stock_level",
        ]:
            row[key] = self._clean_numeric_field(row.get(key))
        return row

    def _clean_available_until_choice(self, val):
        """
        Map the human-readable Excel choice "No end date" to the backend key "no_end_date".
        Leave any other value untouched.
        """
        if isinstance(val, str) and val.strip().lower() == "no end date":
            return "no_end_date"
        return val

    def _clean_numeric_field(self, value):
        if not pd.notna(value):
            return None
        try:
            if isinstance(value, str):
                v = value.strip()
                if "," in v:
                    return ",".join(str(int(float(x))) for x in v.split(","))
                if v.replace(".", "", 1).isdigit():
                    return str(int(float(v)))
            if isinstance(value, (int, float)):
                return str(int(float(value)))
        except Exception as e:
            logger.error(f"Error cleaning numeric field: {e}")
        return None

    def _clean_run_to_zero(self, val):
        if isinstance(val, str):
            return {"y": True, "n": False}.get(val.strip().lower(), False)
        return bool(val) if isinstance(val, bool) else False

    def _clean_invalid_strings(self, row):
        for k, v in row.items():
            if isinstance(v, str) and v.strip().lower() in {"-", "nan", "n/a"}:
                row[k] = None
        return row

    def convert_created_date(self, val):
        # Turn pandas Timestamp into datetime
        if isinstance(val, pd.Timestamp):
            dt = val.to_pydatetime()
        # Already a datetime
        elif isinstance(val, datetime.datetime):
            dt = val
        # Parse string
        elif isinstance(val, str):
            for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S"):
                try:
                    dt = datetime.datetime.strptime(val, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError(f"Unsupported 'created' format: {val!r}")
        else:
            raise ValueError(f"Unsupported 'created' format: {val!r}")

        # If naïve, make it aware in your default timezone
        if timezone.is_naive(dt):
            dt = timezone.make_aware(dt, timezone.get_default_timezone())

        return dt

    def get_publish_date(self, raw):
        if raw and raw != "-":
            if isinstance(raw, datetime.date):
                return raw
            if isinstance(raw, str):
                for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
                    try:
                        return datetime.datetime.strptime(raw, fmt).date()
                    except ValueError:
                        continue
        return datetime.date.today()

    def get_or_create_root_page(self):
        try:
            return Page.objects.get(slug="products-root")
        except Page.DoesNotExist:
            site_root = Page.get_first_root_node()
            if not site_root:
                raise ImproperlyConfigured("Cannot find a root page in Wagtail.")
            root = ProductUpdate(title="Products Root", slug="products-root")
            site_root.add_child(instance=root)
            return root

    def assign_m2m_fields(self, instance, m2m_mapping, row, add_only=False):
        names = {}
        for col, (attr_name, model, lookup_field, resp_key) in m2m_mapping.items():
            raw = row.get(col)
            manager = getattr(instance, attr_name)
            if not raw:
                if not add_only:
                    manager.clear()
                names[resp_key] = []
                continue
            ids = [v.strip() for v in str(raw).split(",") if v.strip()]
            objs = list(model.objects.filter(**{f"{lookup_field}__in": ids}))
            if add_only:
                existing_ids = set(
                    str(x) for x in manager.values_list(lookup_field, flat=True)
                )
                to_add = [
                    o for o in objs if str(getattr(o, lookup_field)) not in existing_ids
                ]
                if to_add:
                    manager.add(*to_add)
            else:
                manager.set(objs)
            names[resp_key] = [
                getattr(o, "name", str(getattr(o, lookup_field))) for o in objs
            ]
        instance.save()
        return names

    def create_product_update(self, row):
        run = bool(row.get("run_to_zero", False))
        return ProductUpdate(
            title=str(row.get("title", "")),
            slug=f"update-{uuid.uuid4().hex[:8]}",
            minimum_stock_level=row.get("minimum_stock_level"),
            quantity_available=row.get("quantity_available", 0),
            run_to_zero=run,
            available_from_choice=row.get("available_from_choice"),
            available_until_choice=row.get("available_until_choice"),
            order_from_date=row.get("order_from_date"),
            order_end_date=row.get("order_end_date"),
            product_type=row.get("product_type"),
            alternative_type=row.get("alternative_type"),
            cost_centre=row.get("cost_centre"),
            local_code=row.get("local_code"),
            unit_of_measure=row.get("unit_of_measure"),
            summary_of_guidance=row.get("guidance"),
            stock_owner_email_address=row.get("stock_owner"),
            order_referral_email_address=row.get("stock_referral"),
            product_downloads=row.get("product_downloads", {}),
        )

    def create_product(
        self, row, program, language, iso_code, pu, created_at, publish_date
    ):
        user = None
        uid = row.get("user_id")
        if uid:
            user = User.objects.filter(user_id=uid).first()
        slug_base = str(row.get("title", ""))
        return Product(
            title=str(row.get("title", "")),
            slug=f"{slugify(slug_base)}-{uuid.uuid4().hex[:6]}",
            user_ref=user,
            product_id=str(uuid.uuid4()),
            program_name=program.programme_name if program else "",
            product_title=str(row.get("title", "")),
            status=row.get("status"),
            product_code=row.get("product_code"),
            file_url=row.get("gov_related_article"),
            tag=row.get("tag"),
            product_key=row.get("product_key"),
            program_id=program,
            language_id=language,
            version_number="001",
            iso_language_code=iso_code,
            language_name=row.get("language_name"),
            update_ref=pu,
            created_at=created_at,
            is_latest=True,
            publish_date=publish_date,
            suppress_event=False,
        )

    def create_order_limits(self, product, row):
        """
        Create OrderLimitPage entries for any orgs explicitly passed in the sheet,
        then fill in the remaining categories with our defaults.
        """
        DEFAULT_LIMITS = {
            "Private": 5,
            "Private Company": 5,
            "Private Health": 5,
            "Education": 100,
            "Government": 100,
            "Local Government": 500,
            "Social Care": 500,
            "Stake Holder": 100,
            "Voluntary Service": 100,
            "NHS": 500,
        }

        saved = []

        # Parse any explicitly supplied limits from the sheet
        supplied = {}
        raw_names = row.get("organization_names")
        sheet_limit = row.get("order_limit_value")
        if raw_names and pd.notna(sheet_limit):
            for name in str(raw_names).split(","):
                nm = name.strip()
                if nm:
                    supplied[nm] = int(sheet_limit)

        # Helper to create one OrderLimitPage
        def _make_limit(nm, lim_val):
            org = Organization.objects.filter(name=nm).first()
            if not org:
                logger.warning(f"Org '{nm}' not found, skipping limit")
                return
            ol = OrderLimitPage(
                title=f"Order limit for {nm}",
                slug=f"ol-{org.id}-{uuid.uuid4().hex[:6]}",
                order_limit_id=str(uuid.uuid4()),
                order_limit=lim_val,
                product_ref=product,
                organization_ref=org,
            )
            self.safe_add_child(product, ol)
            saved.append(nm)

        # 1) Create pages for any limits explicitly supplied
        for nm, lim in supplied.items():
            _make_limit(nm, lim)

        # 2) Fill in the rest from our DEFAULT_LIMITS
        for nm, default_lim in DEFAULT_LIMITS.items():
            if nm not in supplied:
                _make_limit(nm, default_lim)

        return saved


class ProductViewSet(ProductUtilsMixin, viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request):
        # Load and validate spreadsheet
        df, error_resp = self._load_dataframe(request)
        if error_resp:
            return error_resp

        # Retrieve root page
        root, error_resp = self._get_root_page()
        if error_resp:
            return error_resp

        # Mapping for m2m fields
        m2m_map = {
            "audience_id": ("audience_ref", Audience, "audience_id", "audience_names"),
            "where_to_use_id": (
                "where_to_use_ref",
                WhereToUse,
                "where_to_use_id",
                "where_to_use_names",
            ),
            "vaccination_id": (
                "vaccination_ref",
                Vaccination,
                "vaccination_id",
                "vaccination_names",
            ),
            "disease_id": ("diseases_ref", Disease, "disease_id", "disease_names"),
        }

        skipped = []
        created_count = 0
        order_limits_count = 0

        # Process rows atomically
        with transaction.atomic():
            for idx, row_series in df.iterrows():
                row = row_series.to_dict()
                result = self._process_row(idx, row, root, m2m_map)
                if result.get("skip"):
                    skipped.append(result)
                else:
                    created_count += 1
                    order_limits_count += result.get("order_limits", 0)

        return Response(
            {
                "message": "Bulk upload complete.",
                "created_products": created_count,
                "skipped_rows": skipped,
                "order_limits_created": order_limits_count,
            },
            status=status.HTTP_201_CREATED,
        )

    def _load_dataframe(self, request):
        file = request.FILES.get("product_excel")
        if not file:
            return None, Response(
                {"error": "No merged Excel file uploaded."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            file.seek(0)
            df = pd.read_excel(file, engine="openpyxl").where(
                pd.notna(pd.read_excel(file, engine="openpyxl")), None
            )
        except Exception as e:
            logger.exception("Error reading uploaded file")
            return None, Response(
                {"error": "Could not parse spreadsheet", "details": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if df.empty:
            return None, Response(
                {"message": "Uploaded spreadsheet contains no data rows."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return df, None

    def _get_root_page(self):
        try:
            root = self.get_or_create_root_page()
            return root, None
        except Exception:
            return None, Response(
                {"error": "Unable to find or create products root page."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _process_row(self, idx, row, root, m2m_map):
        """
        Handles creation or skipping of a single product row.
        Returns a dict with skip=True and error info or skip=False and order_limits count.
        """
        try:
            # Required fields
            for field in (
                "product_key",
                "title",
                "language_id",
                "gov_related_article",
                "product_code",
            ):
                if not row.get(field):
                    raise ValueError(f"Missing required {field}")

            row = self.clean_row_data(row)
            created_dt = self.convert_created_date(row.get("created"))
            pub_date = self.get_publish_date(row.get("version_date"))

            # Program lookup
            program = None
            pid = row.get("programme_id")
            if pid:
                program = Program.objects.filter(program_id=str(int(pid))).first()
                if not program:
                    raise ValueError(f"Program {pid} not found")

            # Language lookup
            language = LanguagePage.objects.filter(
                language_id=row["language_id"]
            ).first()
            if not language:
                raise ValueError(f"Language {row['language_id']} not found")
            iso_code = language.iso_language_code.upper()

            code = row["product_code"]
            if Product.objects.filter(product_code=code).exists():
                return {
                    "skip": True,
                    "row": idx + 1,
                    "error": f"Product with code {code} already exists.",
                }

            # Create product update
            pu = self.create_product_update(row)
            self.safe_add_child(root, pu)
            self.assign_m2m_fields(pu, m2m_map, row, add_only=False)

            # Create main product
            prod = self.create_product(
                row, program, language, iso_code, pu, created_dt, pub_date
            )
            self.safe_add_child(root, prod)

            # Create order limits
            ols = self.create_order_limits(prod, row)
            return {"skip": False, "order_limits": len(ols)}

        except Exception as e:
            logger.exception(f"Row {idx+1} error: {e}")
            return {"skip": True, "row": idx + 1, "error": str(e)}


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
        main_download = product_downloads.get("main_download_url")
        if isinstance(main_download, dict):
            s3_url = main_download.get("s3_bucket_url")
            if s3_url:
                urls.append(s3_url)
        for download_type in [
            "web_download_url",
            "print_download_url",
            "transcript_url",
        ]:
            downloads = product_downloads.get(download_type, [])
            if isinstance(downloads, list):
                urls.extend(
                    [
                        item.get("s3_bucket_url")
                        for item in downloads
                        if isinstance(item, dict) and item.get("s3_bucket_url")
                    ]
                )
        return urls

    def _apply_metadata_and_presigned(
        self, item, presigned_urls, inline_presigned_urls, metadata_dict
    ):
        """
        Helper to update a download item with both presigned URLs and file metadata.
        """
        if not isinstance(item, dict):
            return item

        s3_url = item.get("s3_bucket_url", "")
        if s3_url in presigned_urls:
            presigned_url = presigned_urls[s3_url]
            item["URL"] = presigned_url

            # Merge metadata if available
            if metadata_dict and presigned_url in metadata_dict:
                # Merge existing metadata into the item.
                meta = metadata_dict[presigned_url]
                item.update(meta)
            # Always keep the original S3 URL for reference.
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
        OrderLimitPage.objects.filter(product_ref=product).delete()
        org_cache = {}
        parent_page = Page.objects.get(slug="products")
        for limit in order_limits:
            org_name = limit.get("organization_name")
            if not org_name:
                continue
            order_limit_value = limit.get("order_limit_value", 0)
            if org_name not in org_cache:
                try:
                    org_cache[org_name] = Organization.objects.get(name=org_name)
                except Organization.DoesNotExist:
                    logger.warning("Organization %s not found.", org_name)
                    continue
            organization = org_cache[org_name]
            full_keys = list(
                Establishment.objects.filter(organization_ref=organization).values_list(
                    "full_external_key", flat=True
                )
            )
            order_limit_page = OrderLimitPage(
                title=f"Order Limit for {org_name}",
                slug=slugify(f"{org_name}-order-limit-{datetime.datetime.now()}"),
                order_limit=order_limit_value,
                product_ref=product,
                organization_ref=organization,
                full_external_keys=full_keys,
            )
            parent_page.add_child(instance=order_limit_page)

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


class ProductListMixin:
    """
    Handles sorting, pagination + S3 presigning—but now with per-request caching.
    """

    serializer_class = ProductSerializer
    include_request_context = False
    cache_timeout = CACHE_TTL

    def get_cache_key(self, request, prefix="products"):
        user_part = (
            f"user:{request.user.id}" if request.user.is_authenticated else "user:anon"
        )
        return f"{prefix}:{user_part}:{request.get_full_path()}"

    def get_sorted_queryset(self, queryset, request):
        sort_by = request.GET.get("sort_by")
        if sort_by and sort_by.lstrip("-") in VALID_SORT_FIELDS:
            return queryset.order_by(sort_by)
        return queryset

    def get_serializer_context(self, request):
        return {"request": request} if self.include_request_context else {}

    def paginate_and_serialize(
        self, queryset, request, serializer_class=None, use_direct_update=False
    ):
        cache_key = self.get_cache_key(request)
        cached = cache.get(cache_key)
        if cached is not None:
            return cached, None

        paginator = CustomPagination()
        page = paginator.paginate_queryset(queryset, request)
        ctx = self.get_serializer_context(request)
        serializer = (serializer_class or self.serializer_class)(
            page, many=True, context=ctx
        )

        # 1) collect S3 URLs
        all_urls = extract_s3_urls(serializer.data)
        # 2) presign ( caches per-URL internally)
        presigned = generate_presigned_urls(all_urls)

        # 3) inject
        if use_direct_update:
            _update_product_downloads_with_presigned_urls(page, presigned)
            serializer = (serializer_class or self.serializer_class)(
                page, many=True, context=ctx
            )
        else:
            update_product_urls(serializer.data, presigned)

        data = serializer.data
        cache.set(cache_key, data, self.cache_timeout)
        return data, paginator


@method_decorator(cache_page(CACHE_TTL), name="dispatch")
class ProductAdminListView(APIView, ProductListMixin):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    # 👉 Turn on request-injection so the serializer’s to_representation()
    # will see `request.user` and _not_ strip out your email fields.
    include_request_context = True

    def get(self, request, *args, **kwargs):
        logger.info("ProductAdminListView GET called")
        try:
            products = Product.objects.all()
            if not products.exists():
                logger.warning(ErrorMessage.PRODUCT_NOT_FOUND.value)
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            sorted_qs = self.get_sorted_queryset(products, request)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            logger.info("Returning %d products", len(data))
            return paginator.get_paginated_response(
                data, status_code=status.HTTP_200_OK
            )
        except Exception as e:
            return handle_exceptions(e)


@method_decorator(cache_page(CACHE_TTL), name="dispatch")
class ProductUsersListView(APIView, ProductListMixin):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        logger.info("ProductUsersListView GET method called")
        try:
            products = Product.objects.filter(status="live").distinct()
            if not products.exists():
                logger.warning("No published products found.")
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            sorted_qs = self.get_sorted_queryset(products, request)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            data = filter_live_languages(data)
            logger.info("Returning paginated response with %d products", len(data))
            return paginator.get_paginated_response(
                data, status_code=status.HTTP_200_OK
            )
        except Exception as e:
            return handle_exceptions(e)


class ProductSearchListMixin(ProductListMixin):
    """
    A specialized mixin for search endpoints. Inherits the functionality of
    ProductListMixin but overrides the serializer_class to use ProductSearchSerializer.
    """

    serializer_class = ProductSearchSerializer


class BaseProductSearchView(APIView, ProductListMixin):
    pagination_class = CustomPagination

    def get_default_query(self) -> Q:
        """
        Returns the default query for the search.
        Override in subclasses if necessary.
        """
        return Q()

    def postprocess_response_data(self, response_data: dict, products) -> dict:
        """
        Hook to postprocess the response data before returning.
        Override in subclasses to add extra keys.
        """
        return response_data

    def get(self, request, *args, **kwargs) -> Response:
        try:
            # Validate input parameters
            product_code = request.GET.get("product_code")
            product_title = request.GET.get("product_title")
            if product_code and not re.match(PRODUCT_CODE_PATTERN, product_code):
                return _handle_invalid_query_param()
            if product_title and not isinstance(product_title, str):
                return _handle_invalid_query_param()

            # Build the query: start from a default that can be extended by subclasses
            query = self.get_default_query()
            if product_code:
                query &= Q(product_code_no_dashes__icontains=product_code)
            if product_title:
                query &= Q(product_title__icontains=product_title)

            products = Product.objects.filter(query).distinct()
            if not products.exists():
                return Response(
                    {"detail": ErrorMessage.PRODUCT_NOT_FOUND.value},
                    status=status.HTTP_404_NOT_FOUND,
                )

            sorted_qs = self.get_sorted_queryset(products, request)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            response_data = _prepare_response_data(
                products, data, product_code, product_title
            )
            response_data = self.postprocess_response_data(response_data, products)
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
        # Admin view doesn't restrict by latest/live status.
        return Q()

    def postprocess_response_data(self, response_data: dict, products) -> dict:
        # Append recommended products for the admin view.
        response_data["recommended_products"] = get_recommended_products(products)
        return response_data


class ProductSearchUserView(BaseProductSearchView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get_default_query(self) -> Q:
        # User view only shows live, latest products.
        return Q(is_latest=True, status="live")


class ProductUsersSearchFilterAPIView(generics.ListAPIView):
    """
    GET /api/v1/products/user/search/filter/
      ?q=foo
      &audiences=A,B
      &languages=en,fr
      &download_mode=download_only
      &recently_updated=2025-01-01T00:00:00Z
      &ordering=-updated_at
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


class ProductUsersFilterView(APIView, ProductListMixin):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    pagination_class = CustomPagination

    def get(self, request, *args, **kwargs) -> Response:
        try:
            query = self.build_query(request)
            products = Product.objects.filter(
                query, is_latest=True, status="live"
            ).distinct()
            sort_by = request.GET.get("sort_by", "product_title")
            if sort_by not in VALID_SORT_FIELDS:
                sort_by = "product_title"
            sorted_qs = products.order_by(sort_by)
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

    def build_query(self, request):
        query = Q()
        recently_updated = request.GET.get("recently_updated")
        download_or_order = request.GET.get("download_or_order")
        download_only = request.GET.get("download_only")
        order_only = request.GET.get("order_only")
        audience_names = request.GET.getlist("audiences", [])
        program_names = request.GET.getlist("program_names", [])
        disease_names = request.GET.getlist("diseases", [])
        vaccination_names = request.GET.getlist("vaccinations", [])
        product_types = request.GET.getlist("product_type", [])
        language_names = request.GET.getlist("languages", [])
        alternative_type = request.GET.getlist("alternative_type", [])
        where_to_use_names = request.GET.getlist("where_to_use", [])

        if recently_updated:
            query &= self.handle_recently_updated(recently_updated)
        if download_only and download_only.lower() == "true":
            query &= Q(tag__in=["download_only"])
        elif download_or_order and download_or_order.lower() == "true":
            query &= Q(tag__in=["download_and_order"])
        elif order_only and order_only.lower() == "true":
            query &= Q(tag__in=["order_only"])
        if audience_names:
            query &= Q(update_ref__audience_ref__name__in=audience_names)
        if disease_names:
            query &= Q(update_ref__diseases_ref__name__in=disease_names)
        if vaccination_names:
            query &= Q(update_ref__vaccination_ref__name__in=vaccination_names)
        if program_names:
            query &= Q(program_name__in=program_names)
        if where_to_use_names:
            query &= Q(update_ref__where_to_use_ref__name__in=where_to_use_names)
        if alternative_type:
            query &= Q(update_ref__alternative_type__in=alternative_type)
        if product_types:
            query &= Q(update_ref__product_type__in=product_types)
        if language_names:
            query &= Q(language_name__in=language_names)

        return query

    def handle_recently_updated(self, recently_updated):
        try:
            return Q(updated_at__gte=recently_updated)
        except ValueError:
            return _handle_invalid_query_param()


class ProductUsersSearchFilterAPIView(generics.ListAPIView):
    """
    GET /api/v1/products/user/search/filter/
      ?q=foo
      &audiences=A,B
      &languages=en,fr
      &download_mode=download_only
      &recently_updated=2025-01-01T00:00:00Z
      &ordering=-updated_at
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


class ProductAdminFilterView(APIView, ProductListMixin):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    pagination_class = CustomPagination

    def _build_filter_query(self, request):
        filter_mapping = {
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
        query = Q()
        # Process other filters using getlist
        for param, lookup in filter_mapping.items():
            values = request.GET.getlist(param, [])
            if values:
                query &= Q(**{lookup: values})

        # Updated product_code handling for multiple values
        product_codes = request.GET.getlist("product_code")
        if product_codes:
            code_query = Q()
            for code in product_codes:
                code_query |= Q(product_code_no_dashes__icontains=code)
            query &= code_query

        return query

    def get(self, request, *args, **kwargs) -> Response:
        try:
            query = self._build_filter_query(request)
            products = Product.objects.filter(query).distinct()

            sorted_qs = self.get_sorted_queryset(products, request)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            return paginator.get_paginated_response(data)
        except Exception:
            logger.exception(INTERNAL_ERROR_MSG)
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProgramProductsView(ListAPIView):
    """
    GET /api/v1/programmes/<program_id>/products/?page=<n>&sort_by=<field>
    returns:
    {
      links: { next, previous },
      count: <total>,
      results: [ /* products */ ],
      diseases: [ /* disease meta */ ],
      vaccinations: [ /* vaccination meta */ ]
    }
    """

    serializer_class = ProductSerializer
    pagination_class = CustomPagination
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    cache_timeout = CACHE_TTL

    def get_cache_key(self, request, program_id):
        user_part = (
            f"user:{request.user.id}" if request.user.is_authenticated else "user:anon"
        )
        return f"prog_products:{program_id}:{user_part}:{request.get_full_path()}"

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
                Q(program_id=program.pk)
                & (
                    Q(update_ref__diseases_ref__in=diseases)
                    | Q(update_ref__vaccination_ref__in=vaccinations)
                )
                & Q(is_latest=True)
                & Q(status="live")
            )
            .distinct()
        )

    def list(self, request, *args, **kwargs):
        cache_key = self.get_cache_key(request, kwargs["program_id"])
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        page = self.paginate_queryset(self.get_queryset())
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            data = serializer.data

            # presign with TTL & caching
            all_urls = extract_s3_urls(data)
            presigned = generate_presigned_urls(all_urls)
            update_product_urls(data, presigned)

            resp = self.get_paginated_response(data)

            program = get_object_or_404(Program, pk=kwargs["program_id"])
            resp.data["diseases"] = DiseaseSerializer(
                Disease.objects.filter(programs=program), many=True
            ).data
            resp.data["vaccinations"] = VaccinationSerializer(
                Vaccination.objects.filter(programs=program), many=True
            ).data

            cache.set(cache_key, resp.data, self.cache_timeout)
            return resp

        # fallback (no pagination)
        data = self.get_serializer(self.get_queryset(), many=True).data
        cache.set(cache_key, data, self.cache_timeout)
        return Response(data)


class IncompleteProductsView(View):
    def get(self, request, *args, **kwargs):
        # Get the current date and the target date range
        current_date = timezone.now().date()
        target_date = current_date + timedelta(days=7)

        # Query products that are in Draft status and have a publish_date within the next 7 days
        products = Product.objects.filter(
            status="draft",
            publish_date__gt=current_date,
            publish_date__lte=target_date,
        )
        logger.info(
            "Found %d products in Draft status with publish_date within the next 7 days",
            products.count(),
        )

        # Initialize the ProductStatusUpdateView for field checking
        status_update_view = ProductStatusUpdateView()

        incomplete_products = []

        # Iterate over the products and check for incomplete fields
        for product in products:
            missing_fields = status_update_view.check_required_fields(product)

            # If there are missing fields, append the product to the list
            if missing_fields:
                incomplete_products.append(
                    {
                        "tag": product.tag,
                        "product_title": product.product_title,
                        "product_code": product.product_code,
                    }
                )

        # Return the data as JSON
        return JsonResponse(incomplete_products, safe=False)


#
