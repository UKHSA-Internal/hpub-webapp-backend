import datetime
import json
import logging
import re
import uuid
from typing import Optional
from urllib.parse import unquote

import bcp47
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
from core.roles.models import Role
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

from core.utils.product_recommendation_system import get_recommended_products
from core.vaccinations.models import Vaccination
from core.vaccinations.serializers import VaccinationSerializer
from core.where_to_use.models import WhereToUse
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from rest_framework.exceptions import ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
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
from .serializers import ProductSerializer, ProductUpdateSerializer
from django.core.serializers.json import DjangoJSONEncoder


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


def get_bcp47_language_code(language_name):
    try:
        # Retrieve the BCP 47 language code
        language_code = bcp47.languages.get(language_name)
        if not language_code:
            return "UNKNOWN"

        # Convert to uppercase and replace hyphen with underscore
        language_code = language_code.upper().replace("-", "_")
        return language_code
    except Exception as e:
        logger.error(f"Error retrieving BCP 47 language code: {str(e)}")
        return "UNKNOWN"


def check_user_permission(user, permission):
    # Fetch the user's roles and check permissions
    user_roles = Role.objects.filter(pages__in=user.page_set.all())
    for role in user_roles:
        if permission in [perm["value"] for perm in role.permissions.stream_data]:
            return True
    return False


def product_view(request, product_id):
    if not check_user_permission(request.user, "view_product"):
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    # Your logic to handle product viewing
    product = get_object_or_404(Product, id=product_id)
    serializer = ProductSerializer(product)
    return Response(serializer.data, status=status.HTTP_200_OK)


def create_product(request):
    if not check_user_permission(request.user, "create_product"):
        return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

    # Your logic to handle product creation
    data = request.data
    serializer = ProductSerializer(data=data)
    if serializer.is_valid():
        serializer.save()
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


def generate_product_key(last_key=None):
    """
    Generates the next product_key in sequence from 1-9, then A-Z.

    Args:
        last_key (str): The last used product_key. If None, starts with '1'.

    Returns:
        str: The next product_key.
    """
    if last_key is None:
        return "1"  # Start with '1' if no last_key is provided

    # Handle single digits 1-9
    if last_key.isdigit() and int(last_key) < 9:
        return str(int(last_key) + 1)

    # Handle transition from 9 to A
    if last_key == "9":
        return "A"

    # Handle letters A-Z
    if last_key.isalpha() and last_key != "Z":
        return chr(ord(last_key) + 1)

    # If last_key was 'Z', raise an exception (or handle the overflow if necessary)
    if last_key == "Z":
        raise ValueError("No more product keys available. Maximum limit 'Z' reached.")

    raise ValueError(f"Invalid last_key: {last_key}")


def get_next_product_key(program_name):
    """
    Retrieves the next available product_key for a given program_id.

    Args:
        program_id (int): The ID of the program to generate a product_key for.

    Returns:
        str: The next available product_key.
    """

    last_product = (
        Product.objects.filter(program_name=program_name)
        .order_by("-product_key")
        .first()
    )
    logging.info("last product:", last_product)

    if last_product:
        last_key = last_product.product_key
    else:
        last_key = None  # No products exist yet for this program

    next_key = generate_product_key(last_key)
    logging.info(f"Last Key: {last_key}, Next Key: {next_key}")  # Debug print
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
            print("Failed to parse product_downloads JSON:", e)
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


class PresignedUrlMixin:
    """Handles presigned URL extraction and injection."""

    def _process_presigned_urls(self, response_data):
        update_refs = response_data.get("update_ref")
        if not isinstance(update_refs, dict):
            return

        product_downloads = update_refs.get("product_downloads")
        if not isinstance(product_downloads, dict):
            return

        all_download_urls = self._collect_s3_urls(product_downloads)
        logger.info(LOG_MSG_S3_URL_EXTRACTION, all_download_urls)

        presigned_urls = generate_presigned_urls(all_download_urls)
        inline_presigned_urls = generate_inline_presigned_urls(all_download_urls)

        if "main_download_url" in product_downloads:
            product_downloads["main_download_url"] = self._process_main_download(
                product_downloads.get("main_download_url"),
                presigned_urls,
                inline_presigned_urls,
            )

        for download_type in [
            "web_download_url",
            "print_download_url",
            "transcript_url",
        ]:
            downloads = product_downloads.get(download_type, [])
            if isinstance(downloads, list):
                product_downloads[download_type] = [
                    self._process_download_item(
                        item, presigned_urls, inline_presigned_urls
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

    def _process_main_download(
        self, main_download, presigned_urls, inline_presigned_urls
    ):
        if not isinstance(main_download, dict):
            return main_download
        s3_url = main_download.get("s3_bucket_url", "")
        if s3_url in presigned_urls:
            main_download["URL"] = presigned_urls[s3_url]
        if (
            not main_download.get("inline_presigned_s3_url")
            and s3_url in inline_presigned_urls
        ):
            main_download["inline_presigned_s3_url"] = inline_presigned_urls[s3_url]
        return main_download

    def _process_download_item(self, item, presigned_urls, inline_presigned_urls):
        if not isinstance(item, dict):
            return item
        s3_url = item.get("s3_bucket_url", "")
        if s3_url in presigned_urls:
            item["URL"] = presigned_urls[s3_url]
        if not item.get("inline_presigned_s3_url") and s3_url in inline_presigned_urls:
            item["inline_presigned_s3_url"] = inline_presigned_urls[s3_url]
        return item


class ProductUtilsMixin:
    """
    Contains common helper functions for product processing,
    used in bulk uploads.
    """

    def skip_row(self, index, message):
        logger.warning(f"Skipping row {index + 1}: {message}")
        return {"skipped": True, "error": {"row": index + 1, "error": message}}

    def assign_m2m_fields(self, instance, m2m_mapping, row):
        m2m_names = {}
        for field_key, (attr_name, model, response_key) in m2m_mapping.items():
            instances, names = self.fetch_instances_and_names(
                model, field_key, row.get(field_key)
            )
            getattr(instance, attr_name).set(instances)
            m2m_names[response_key] = names
        return m2m_names

    def create_product_update(self, row):
        slug_update = f"bulkupload-{uuid.uuid4()}"
        data = {
            "title": row["title"],
            "slug": slug_update,
            "minimum_stock_level": row.get("minimum_stock_level"),
            "maximum_order_quantity": row.get("maximum_order_quantity"),
            "quantity_available": row.get("quantity_available", 0),
            "run_to_zero": row.get("run_to_zero", False),
            "available_from_choice": row.get("available_from_choice", "immediately"),
            "order_from_date": row.get("order_from_date"),
            "order_end_date": row.get("order_end_date"),
            "product_type": row.get("product_type"),
            "alternative_type": row.get("alternative_type"),
            "cost_centre": row.get("cost_centre", "10200"),
            "local_code": row.get("local_code", "0001"),
            "unit_of_measure": row.get("unit_of_measure"),
            "summary_of_guidance": row.get("summary_of_guidance"),
            "stock_owner_email_address": row.get("stock_owner"),
            "order_referral_email_address": row.get("stock_referral"),
            "product_downloads": row.get("product_downloads", {}),
        }
        return ProductUpdate(**data)

    def create_product(
        self,
        row,
        program,
        language,
        iso_language_code,
        product_update,
        created_date,
        publish_date,
    ):
        slug = f"{slugify(row['title'])}-{row['product_id']}-{uuid.uuid4()}"
        data = {
            "title": row["title"],
            "slug": slug,
            "product_id": row["product_id"],
            "program_name": program.programme_name if program else "",
            "product_title": row["title"],
            "status": row["status"],
            "product_code": row["product_code"],
            "file_url": row["gov_related_article"],
            "tag": row["tag"],
            "product_key": 1,
            "program_id": program,
            "language_id": language,
            "version_number": "001",
            "iso_language_code": iso_language_code,
            "language_name": row["language_name"],
            "update_ref": product_update,
            "created_at": created_date,
            "is_latest": True,
            "publish_date": publish_date,
        }
        return Product(**data)

    def process_row(self, row, index, root_page):
        try:
            logger.info(f"Processing row {index + 1}: {row.to_dict()}")
            required_fields = [
                "product_id",
                "title",
                "language_id",
                "gov_related_article",
            ]
            missing_fields = [f for f in required_fields if pd.isna(row.get(f))]
            if missing_fields:
                return self.skip_row(index, f"Missing fields: {missing_fields}")

            if Product.objects.filter(product_id=row["product_id"]).exists():
                return self.skip_row(
                    index, f"Product with id {row['product_id']} already exists."
                )

            row = self.clean_row_data(row)
            logger.debug(f"Cleaned row {index + 1}: {row}")
            row.setdefault("run_to_zero", False)
            created_date = self.convert_created_date(row["created"])

            program = None
            if row.get("programme_id"):
                program_id = (
                    str(int(row["programme_id"]))
                    if pd.notna(row["programme_id"])
                    else None
                )
                logger.info("PROGRAM_ID %s", program_id)
                program = Program.objects.filter(program_id=program_id).first()
                if not program:
                    return self.skip_row(
                        index, f"Program with id {row['programme_id']} does not exist."
                    )

            try:
                language = LanguagePage.objects.get(language_id=row["language_id"])
            except LanguagePage.DoesNotExist:
                return self.skip_row(
                    index, f"Language with id {row['language_id']} does not exist."
                )
            iso_language_code = language.iso_language_code.upper()

            product_update = self.create_product_update(row)
            root_page.add_child(instance=product_update)

            m2m_mapping = {
                "audience_id": ("audience_ref", Audience, "audience_names"),
                "where_to_use_id": (
                    "where_to_use_ref",
                    WhereToUse,
                    "where_to_use_names",
                ),
                "vaccination_id": ("vaccination_ref", Vaccination, "vaccination_names"),
                "disease_id": ("diseases_ref", Disease, "disease_names"),
            }
            m2m_names = self.assign_m2m_fields(product_update, m2m_mapping, row)
            product_update.save()

            publish_date = self.get_publish_date(row.get("version_date"), index)
            product = self.create_product(
                row,
                program,
                language,
                iso_language_code,
                product_update,
                created_date,
                publish_date,
            )
            root_page.add_child(instance=product)

            order_limits_list = self.build_order_limits(
                row.get("organization_name"), row.get("order_limit_value")
            )
            logger.info(
                "Final response for product_id %s: %s",
                product.product_id,
                {
                    "audience_names": m2m_names.get("audience_names", []),
                    "vaccination_names": m2m_names.get("vaccination_names", []),
                    "disease_names": m2m_names.get("disease_names", []),
                    "where_to_use_names": m2m_names.get("where_to_use_names", []),
                    "order_limits": order_limits_list,
                },
            )
            # Two pages created: product_update and product.
            return {"skipped": False, "products_created": 2}

        except (Program.DoesNotExist, LanguagePage.DoesNotExist, ValueError) as ve:
            logger.warning(f"Data error in row {index + 1}: {ve}")
            return self.skip_row(index, str(ve))
        except Exception as e:
            logger.exception(f"Unexpected error in row {index + 1}: {e}")
            return self.skip_row(index, f"Unexpected error: {str(e)}")

    def get_publish_date(self, raw_version_date, index):
        publish_date = None
        if raw_version_date and raw_version_date != "-":
            try:
                if isinstance(raw_version_date, datetime.date):
                    publish_date = raw_version_date
                else:
                    publish_date = datetime.datetime.strptime(
                        raw_version_date, "%Y-%m-%d"
                    ).date()
            except ValueError:
                logger.warning(
                    f"Invalid publish_date format for row {index + 1}: {raw_version_date}"
                )
                publish_date = None
        if publish_date is None:
            publish_date = datetime.date.today()
        return publish_date

    def build_order_limits(self, organization_names_str, max_val):
        order_limits_list = []
        if organization_names_str:
            for org_name in (
                org.strip() for org in organization_names_str.split(",") if org.strip()
            ):
                order_limits_list.append(
                    {"organization_name": org_name, "order_limit_value": max_val}
                )
        return order_limits_list

    def _clean_numeric_field(self, value):
        if not pd.notna(value):
            return None
        try:
            if isinstance(value, str):
                value = value.strip()
                if "," in value:
                    return ",".join(
                        str(int(float(item.strip())))
                        if item.strip().replace(".", "", 1).isdigit()
                        else item.strip()
                        for item in value.split(",")
                    )
                if value.replace(".", "", 1).isdigit():
                    return str(int(float(value)))
            elif isinstance(value, (int, float)):
                return str(int(float(value)))
        except ValueError:
            return None
        return None

    def _clean_run_to_zero(self, val):
        if isinstance(val, str):
            return {"y": True, "n": False}.get(val.strip().lower())
        return val

    def _clean_invalid_strings(self, row_dict):
        for key, value in row_dict.items():
            if isinstance(value, str) and value.strip().lower() in {"-", "nan"}:
                row_dict[key] = None
        return row_dict

    def clean_row_data(self, row):
        row["run_to_zero"] = self._clean_run_to_zero(row.get("run_to_zero"))
        row = self._clean_invalid_strings(row)
        numeric_fields = [
            "product_id",
            "unit_of_measure",
            "programme_id",
            "language_id",
            "audience_id",
            "where_to_use_id",
            "vaccination_id",
            "disease_id",
            "minimum_stock_level",
        ]
        for key in numeric_fields:
            row[key] = self._clean_numeric_field(row.get(key))
        return row

    def convert_created_date(self, created_date_str):
        if isinstance(created_date_str, pd.Timestamp):
            return created_date_str.to_pydatetime()
        elif isinstance(created_date_str, str):
            return datetime.datetime.strptime(created_date_str, "%d/%m/%Y %H:%M:%S")
        else:
            raise ValueError(
                f"Unsupported type for 'created': {type(created_date_str)}"
            )

    def get_or_create_root_page(self):
        try:
            root_page = Page.objects.get(slug="products-root")
            logger.info("Root page 'products-root' found.")
        except Page.DoesNotExist:
            logger.warning("Root page 'products-root' not found. Creating it.")
            wagtail_root = Page.objects.filter(depth=1).first()
            if not wagtail_root:
                raise ImproperlyConfigured(
                    "Wagtail root page not found. Check Wagtail setup."
                )
            root_page = ProductUpdate(title="Products Root", slug="products-root")
            wagtail_root.add_child(instance=root_page)
            logger.info("Root page 'products-root' created successfully.")
        return root_page

    def fetch_instances_and_names(self, model, field_name, ids_str):
        if not ids_str:
            return [], []
        ids = [id_val.strip() for id_val in ids_str.split(",") if id_val.strip()]
        if not ids:
            return [], []
        instances = model.objects.filter(**{f"{field_name}__in": ids})
        names = [inst.name for inst in instances]
        return list(instances), names


class ProductViewSet(ProductUtilsMixin, viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request):
        """
        Bulk upload for merged product Excel files.
        Reads each row and creates Product / ProductUpdate records.
        """
        try:
            with transaction.atomic():
                logger.info("Starting bulk upload of merged product Excel to DB...")

                merged_excel_file = request.FILES.get("product_excel")
                if not merged_excel_file:
                    logger.error("No merged Excel file uploaded.")
                    return Response(
                        {"error": "No merged Excel file uploaded."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                try:
                    df = pd.read_excel(merged_excel_file)
                    df = df.where(pd.notna(df), None)
                except Exception as e:
                    logger.error(f"Error reading merged Excel file: {str(e)}")
                    return Response(
                        {"error": "Invalid Excel file."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                skipped_rows = []
                created_products = 0
                root_page = self.get_or_create_root_page()

                for index, row in df.iterrows():
                    result = self.process_row(row, index, root_page)
                    if result.get("skipped"):
                        skipped_rows.append(result["error"])
                    else:
                        created_products += result.get("products_created", 0)

                logger.info(f"Bulk upload completed. Rows skipped: {len(skipped_rows)}")
                return Response(
                    {
                        "message": "Bulk upload of merged product Excel completed.",
                        "created_products": created_products,
                        "skipped_rows": skipped_rows,
                    },
                    status=status.HTTP_201_CREATED,
                )

        except Exception as e:
            logger.exception("An unexpected error occurred during bulk upload.")
            return Response(
                {"error": f"Unexpected error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class ProductDetailView(ErrorHandlingMixin, PresignedUrlMixin, viewsets.ViewSet):
    """
    A view for returning product details.
    Note: This example uses ViewSet for consistency, but you can also use a plain View.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def retrieve(self, request, product_code=None, *args, **kwargs):
        product_code = unquote(product_code)
        logger.info("Fetching details for product with product_code: %s", product_code)

        product = Product.objects.filter(product_code=product_code).first()
        if not product:
            logger.warning(PRODUCT_NOT_FOUND_LOG_MSG, product_code)
            return handle_error(
                ErrorCode.PRODUCT_NOT_FOUND,
                ErrorMessage.PRODUCT_NOT_FOUND,
                status_code=status.HTTP_404_NOT_FOUND,
            )

        serializer = ProductSerializer(product)
        response_data = serializer.data

        # Process presigned URLs via the mixin.
        self._process_presigned_urls(response_data)

        logger.info("Returning product details for product_code: %s", product_code)
        return JsonResponse(response_data, status=200)


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
        "live": ["archived", "withdrawn"],
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

            product.status = new_status
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
                ErrorCode.DATABASE_ERROR
                if isinstance(e, DatabaseError)
                else ErrorCode.TIMEOUT_ERROR,
                ErrorMessage.DATABASE_ERROR
                if isinstance(e, DatabaseError)
                else ErrorMessage.TIMEOUT_ERROR,
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
            serializer = ProductSerializer(product, data=data, partial=True)
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


class ProductPatchView(ErrorHandlingMixin, View):
    """
    Optimized view to handle product updates via PATCH requests.
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
        product_type = data.get("product_type")
        product_downloads = data.get("product_downloads", {})

        # Process file URLs (validation, metadata, presigned URL generation)
        file_urls = self.process_file_urls(product_type, product_downloads)

        # Validate date fields based on provided choices
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

        # Prepare additional update data for the ProductUpdate instance
        product_update_data = self.prepare_product_update_data(
            data,
            available_until_choice,
            available_from_choice,
            order_from_date,
            order_end_date,
            file_urls,
        )

        with transaction.atomic():
            if data.get("order_limits"):
                self.update_order_limits(product, data.get("order_limits"))

            serializer = ProductSerializer(product, data=data, partial=True)
            if serializer.is_valid():
                updated_product = serializer.save()
                if updated_product.update_ref:
                    self.update_foreign_keys(updated_product.update_ref, data)

                self.get_or_create_product_update(product, product_update_data, data)
                response_data = serializer.data
                if updated_product.update_ref:
                    response_data["update_ref"] = ProductUpdateSerializer(
                        updated_product.update_ref
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

    def process_file_urls(self, product_type: str, product_downloads: dict) -> dict:
        """
        Process file URLs by validating required downloads, initializing URLs,
        validating file extensions, and adding metadata (including presigned URLs).
        """
        if isinstance(product_downloads, str):
            try:
                product_downloads = json.loads(product_downloads)
            except json.JSONDecodeError:
                raise ValidationError("Invalid JSON format for product_downloads")

        self.validate_required_downloads(product_type, product_downloads)
        file_urls = self.initialize_file_urls(product_downloads)
        file_urls = self.validate_file_extensions(file_urls)
        return self.add_file_metadata(file_urls)

    def validate_required_downloads(self, product_type: str, product_downloads: dict):
        required = {
            "Audio": ["main_download", "web_download", "transcript"],
            "Bulletins": ["main_download", "print_download", "web_download"],
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
        if product_type in required:
            missing = [d for d in required[product_type] if d not in product_downloads]
            if missing:
                raise ValidationError(
                    f"Missing required downloads for {product_type}: {', '.join(missing)}."
                )

    def initialize_file_urls(self, product_downloads: dict) -> dict:
        return {
            "main_download_url": product_downloads.get("main_download", ""),
            "web_download_url": product_downloads.get("web_download", []),
            "print_download_url": product_downloads.get("print_download", []),
            "transcript_url": product_downloads.get("transcript", []),
            "video_url": product_downloads.get("video_url", ""),
        }

    def validate_file_extensions(self, file_urls: dict) -> dict:
        allowed = {
            "main_download_url": ["jpg", "jpeg", "png", "gif"],
            "transcript_url": ["pdf", "txt", "srt"],
            "web_download_url": [
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
        if file_urls["main_download_url"]:
            ext = file_urls["main_download_url"].split(".")[-1]
            if ext not in allowed["main_download_url"]:
                file_urls["main_download_url"] = ""
        for key in ["web_download_url", "print_download_url", "transcript_url"]:
            file_urls[key] = [
                url
                for url in file_urls[key]
                if url.split(".")[-1] in allowed.get(key, [])
            ]
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
        if update_data.get("run_to_zero"):
            update_data["minimum_stock_level"] = 0
        return update_data

    def get_or_create_product_update(
        self, product: Product, update_data: dict, raw_data: dict
    ) -> ProductUpdate:
        product_update = product.update_ref
        if not product_update:
            logger.info("Creating new ProductUpdate instance.")
            parent_page = product.get_parent()
            product_update = ProductUpdate(**update_data)
            parent_page.add_child(instance=product_update)
            product_update.save_revision().publish()
            Product.objects.filter(pk=product.pk).update(update_ref=product_update)
        else:
            logger.info("Updating existing ProductUpdate instance.")
            for key, value in update_data.items():
                if key in raw_data:
                    setattr(product_update, key, value)
            product_update.save()
        return product_update

    def update_order_limits(self, product: Product, order_limits: list):
        """
        Update order limits associated with the product.
        This method deletes existing order limits and creates new ones individually,
        as bulk_create is not supported for multi-table inherited models.
        """
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
        publish_date = data.get("publish_date") or timezone.now().date()

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
            product_title__icontains=product_title,
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
            data, program, parent_page, user_instance
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
            program_name=program.programme_name, product_title__icontains=product_title_
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
        if existing_product:
            Product.objects.filter(
                product_key=existing_product.product_key,
                language_id=language_id,
                is_latest=True,
            ).update(is_latest=False, status="archived")
            logger.info(
                "Previous versions archived for product_key: %s",
                existing_product.product_key,
            )
        else:
            logger.info("No existing product found; no versions archived.")

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

    def create_product_instance(self, data, program, parent_page, user_instance):
        serializer = ProductSerializer(data=data)
        if serializer.is_valid():
            try:
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
                )
                parent_page.add_child(instance=product_instance)
                logger.info("Product instance created successfully.")
                return product_instance
            except Exception as ex:
                logger.error("Error creating product instance: %s", str(ex))
                return None
        else:
            logger.error("Serializer errors: %s", serializer.errors)
            handle_error(
                ErrorCode.INVALID_DATA, ErrorMessage.INVALID_DATA, status_code=400
            )
            return None


class ProductListMixin:
    serializer_class = ProductSerializer

    def get_sorted_queryset(self, queryset, request):
        sort_by = request.GET.get("sort_by")
        if sort_by in VALID_SORT_FIELDS:
            return queryset.order_by(sort_by)
        return queryset

    def paginate_and_serialize(
        self, queryset, request, serializer_class=None, use_direct_update=False
    ):
        serializer_class = serializer_class or self.serializer_class
        paginator = CustomPagination()
        paginated = paginator.paginate_queryset(queryset, request)

        # Serialize once and batch-process S3 URLs
        serializer = serializer_class(paginated, many=True)
        all_download_urls = extract_s3_urls(serializer.data)
        presigned_urls = generate_presigned_urls(all_download_urls)

        if use_direct_update:
            _update_product_downloads_with_presigned_urls(paginated, presigned_urls)
            serializer = serializer_class(paginated, many=True)
        else:
            update_product_urls(serializer.data, presigned_urls)

        return serializer.data, paginator


class ProductAdminListView(APIView, ProductListMixin):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, *args, **kwargs):
        logger.info("ProductAdminListView GET method called")
        try:
            products = Product.objects.all()
            if not products.exists():
                logger.warning(ErrorMessage.PRODUCT_NOT_FOUND)
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            sorted_qs = self.get_sorted_queryset(products, request)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            logger.info("Returning paginated response with %d products", len(data))
            return paginator.get_paginated_response(
                data, status_code=status.HTTP_200_OK
            )
        except Exception as e:
            return handle_exceptions(e)


class ProductUsersListView(APIView, ProductListMixin):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        logger.info("ProductUsersListView GET method called")
        try:
            products = Product.objects.filter(status="live")
            if not products.exists():
                logger.warning("No published products found.")
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            sorted_qs = self.get_sorted_queryset(products, request)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            data = self.filter_languages(data)
            logger.info("Returning paginated response with %d products", len(data))
            return paginator.get_paginated_response(
                data, status_code=status.HTTP_200_OK
            )
        except Exception as e:
            return handle_exceptions(e)

    def filter_languages(self, products_data):
        # Gather all language product codes in one pass
        product_codes = {
            lang["product_url"].split("/")[-1]
            for product in products_data
            for lang in product.get("existing_languages", [])
        }
        # Bulk query to check which codes are live
        live_codes = set(
            Product.objects.filter(
                product_code__in=product_codes, status="live"
            ).values_list("product_code", flat=True)
        )
        # Filter the languages in memory
        for product in products_data:
            product["existing_languages"] = [
                lang
                for lang in product.get("existing_languages", [])
                if lang["product_url"].split("/")[-1] in live_codes
            ]
        return products_data


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

            products = Product.objects.filter(query)
            if not products.exists():
                return Response(
                    {"detail": ErrorMessage.PRODUCT_NOT_FOUND},
                    status=status.HTTP_404_NOT_FOUND,
                )

            sorted_qs = self.get_sorted_queryset(products, request)
            data, paginator = self.paginate_and_serialize(
                sorted_qs, request, use_direct_update=True
            )
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


class ProductUsersFilterView(APIView, ProductListMixin):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    pagination_class = CustomPagination

    def get(self, request, *args, **kwargs) -> Response:
        try:
            query = self.build_query(request)
            products = Product.objects.filter(query, is_latest=True, status="live")
            sort_by = request.GET.get("sort_by", "product_title")
            if sort_by not in VALID_SORT_FIELDS:
                sort_by = "product_title"
            sorted_qs = products.order_by(sort_by)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            data = self.filter_languages(data)
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

    def filter_languages(self, products_data):
        product_codes = {
            lang["product_url"].split("/")[-1]
            for product in products_data
            for lang in product.get("existing_languages", [])
        }
        live_codes = set(
            Product.objects.filter(
                product_code__in=product_codes, status="live"
            ).values_list("product_code", flat=True)
        )
        for product in products_data:
            product["existing_languages"] = [
                lang
                for lang in product.get("existing_languages", [])
                if lang["product_url"].split("/")[-1] in live_codes
            ]
        return products_data


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
        for param, lookup in filter_mapping.items():
            values = request.GET.getlist(param, [])
            if values:
                query &= Q(**{lookup: values})
        product_code = request.GET.get("product_code", None)
        if product_code:
            query &= Q(product_code_no_dashes__icontains=product_code)
        return query

    def get(self, request, *args, **kwargs) -> Response:
        try:
            query = self._build_filter_query(request)
            products = Product.objects.filter(query)
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


class ProgramProductsView(APIView, ProductListMixin):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get_program_related_data(self, program):
        """
        Fetches related diseases and vaccinations for a given program.
        """
        diseases = Disease.objects.filter(programs=program)
        vaccinations = Vaccination.objects.filter(programs=program)
        return diseases, vaccinations

    def get_program_products(self, program, diseases, vaccinations):
        """
        Builds the products queryset for a given program using related diseases and vaccinations.
        """
        diseases_q = Q(update_ref__diseases_ref__in=diseases)
        vaccinations_q = Q(update_ref__vaccination_ref__in=vaccinations)
        return (
            Product.objects.filter(
                Q(program_id=program) & (diseases_q | vaccinations_q)
            )
            .distinct()
            .prefetch_related("update_ref__diseases_ref", "update_ref__vaccination_ref")
        )

    def get(self, request, program_id):
        try:
            # Get program or raise 404.
            program = get_object_or_404(Program, pk=program_id)
            # Fetch related data.
            diseases, vaccinations = self.get_program_related_data(program)
            # Build products queryset.
            products_qs = self.get_program_products(program, diseases, vaccinations)
            # Sort and paginate.
            sorted_qs = self.get_sorted_queryset(products_qs, request)
            data, paginator = self.paginate_and_serialize(sorted_qs, request)
            # Process S3 URLs.
            all_urls = extract_s3_urls(data)
            presigned_urls = generate_presigned_urls(all_urls)
            update_product_urls(data, presigned_urls)
            # Prepare response.
            response_data = {
                "products": data,
                "diseases": DiseaseSerializer(diseases, many=True).data,
                "vaccinations": VaccinationSerializer(vaccinations, many=True).data,
            }
            return paginator.get_paginated_response(
                response_data, status_code=status.HTTP_200_OK
            )
        except Http404:
            return Response(
                {"detail": "Program not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except Exception as e:
            logger.exception(
                "An error occurred while fetching program products: %s", str(e)
            )
            return Response(
                {"detail": UNEXPECTED_ERROR_MSG},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


#
