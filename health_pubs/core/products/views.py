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
from core.utils.generate_s3_presigned_url import generate_presigned_urls

from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from core.utils.product_recommendation_system import get_recommended_products
from core.vaccinations.models import Vaccination
from core.vaccinations.serializers import VaccinationSerializer
from core.where_to_use.models import WhereToUse
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import DatabaseError, transaction
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from django.views import View
from pydantic import BaseModel, ValidationError, validator
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

from .enums import required_event_fields_archived
from .models import Product, ProductUpdate
from .serializers import ProductSerializer, ProductUpdateSerializer
from .signals import send_product_event


logger = logging.getLogger(__name__)

PRODUCT_CODE_PATTERN = r"^[A-Za-z0-9_-]+$"
# Constants for log messages
LOG_MSG_S3_URL_EXTRACTION = "Extracted S3 URLs for presigned URL generation: %s"
UNEXPECTED_ERROR_MSG = "An unexpected error occurred."
INTERNAL_ERROR_MSG = "An unexpected error occurred while searching for products."


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
    # Extract main_download_url
    main_download = product_downloads.get("main_download_url")
    if isinstance(main_download, dict):
        s3_url = main_download.get("s3_bucket_url")
        if s3_url:
            urls.append(s3_url)

    # Extract other download types
    for key in ["web_download_url", "print_download_url", "transcript_url"]:
        downloads = product_downloads.get(key, [])
        if isinstance(downloads, list):
            for item in downloads:
                if isinstance(item, dict):
                    s3_url = item.get("s3_bucket_url")
                    if s3_url:
                        urls.append(s3_url)
    return urls


def _update_downloads_with_presigned(product_downloads, presigned_urls):
    """Helper to update product_downloads dict with presigned URLs.

    Returns True if any update was performed.
    """
    updated = False
    # Update main_download_url
    main_download = product_downloads.get("main_download_url")
    if isinstance(main_download, dict):
        s3_url = main_download.get("s3_bucket_url", "")
        if s3_url in presigned_urls:
            main_download["URL"] = presigned_urls[s3_url]
            updated = True

    # Update additional download types
    for key in ["web_download_url", "print_download_url", "transcript_url"]:
        downloads = product_downloads.get(key, [])
        if isinstance(downloads, list):
            for item in downloads:
                s3_url = item.get("s3_bucket_url", "")
                if s3_url in presigned_urls:
                    item["URL"] = presigned_urls[s3_url]
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


def _collect_download_urls(products):
    """Collect all download URLs from products for presigned URL generation."""
    all_download_urls = []
    for product in products:
        product_update = product.update_ref  # Assuming update_ref is an attribute
        if product_update:
            product_downloads = product_update.product_downloads
            all_download_urls.extend(_extract_urls_from_downloads(product_downloads))
    return all_download_urls


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


def _prepare_response_data(products, serializer, product_code, product_title):
    matched_titles = list(products.values_list("product_title", flat=True))
    matched_codes = list(products.values_list("product_code", flat=True))
    response_data = {
        "matched_product_titles": matched_titles if product_title else None,
        "matched_product_codes": matched_codes if product_code else None,
        "product_info": list(serializer.data),
    }
    return response_data


def get_product(product_code: str) -> Optional[Product]:
    """Fetch the latest version of the product by its product code.
    Returns None if the product is not found.
    """
    try:
        product = (
            Product.objects.filter(product_code__startswith=product_code)
            .order_by("-version_number")
            .first()
        )
        return product
    except Product.DoesNotExist:
        return None


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
    page_size = 20  # Set pagination to 20 items per page

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


class ProductSchema(BaseModel):
    product_id: str
    title: str
    content_type: str
    status: str
    created: datetime.datetime
    unit_of_measure: str
    description: str
    gov_related_article: str
    product_code: str
    version_date: str
    guidance: str
    stock_owner: str
    stock_referral: str
    tag: str
    programme_id: str
    language_id: str
    language_name: str
    audience_id: str
    where_to_use_id: str
    vaccination_id: str
    disease_id: str

    @validator("created", pre=True, allow_reuse=True)
    def parse_created(cls, value):
        # Handle pandas.Timestamp directly
        if isinstance(value, pd.Timestamp):
            return value.to_pydatetime()
        # Handle string-based date parsing
        elif isinstance(value, str):
            try:
                return datetime.datetime.strptime(value, "%d/%m/%Y %H:%M:%S")
            except ValueError:
                raise ValueError(
                    f"Invalid date format for 'created': {value}. Expected format: DD/MM/YYYY HH:MM:SS"
                )
        else:
            raise ValueError(f"Unsupported type for 'created': {type(value)}")


class ProductViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request):
        try:
            with transaction.atomic():
                logger.info("Starting bulk upload of products to DB...")

                # Validate and read the uploaded file
                excel_file = request.FILES.get("product_excel")
                if not excel_file:
                    logger.error("No Excel file uploaded.")
                    return Response(
                        {"error": "No Excel file uploaded."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                try:
                    df = pd.read_excel(excel_file)
                    df = df.where(pd.notna(df), None)
                except Exception as e:
                    logger.error(f"Error reading Excel file: {str(e)}")
                    return Response(
                        {"error": "Invalid Excel file."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                skipped_rows = []
                created_products = 0

                # Ensure the root page exists or create it
                root_page = self.get_or_create_root_page()

                for index, row in df.iterrows():
                    try:
                        logger.info(f"Processing row {index + 1}: {row.to_dict()}")

                        # Manual Validation
                        required_fields = [
                            "product_id",
                            "title",
                            "language_id",
                            "gov_related_article",
                        ]
                        missing_fields = [
                            field
                            for field in required_fields
                            if pd.isna(row.get(field))
                        ]
                        if missing_fields:
                            logger.warning(
                                f"Skipping row {index + 1}: Missing required fields {missing_fields}"
                            )
                            skipped_rows.append(
                                {
                                    "row": index + 1,
                                    "error": f"Missing fields: {missing_fields}",
                                }
                            )
                            continue

                        # Check for duplicate product_id
                        if Product.objects.filter(
                            product_id=row["product_id"]
                        ).exists():
                            logger.warning(
                                f"Skipping row {index + 1}: Product with id {row['product_id']} already exists."
                            )
                            skipped_rows.append(
                                {
                                    "row": index + 1,
                                    "error": f"Product with id {row['product_id']} already exists.",
                                }
                            )
                            continue

                        # Data Cleaning and Conversion
                        row = self.clean_row_data(row)
                        logger.debug(f"Cleaned row {index + 1}: {row}")

                        # Handle date conversion
                        created_date = self.convert_created_date(row["created"])
                        print("program_id", row["programme_id"])

                        # Fetch related data if 'programme_id' exists
                        program = None
                        if row.get("programme_id"):
                            program_id = (
                                str(int(row["programme_id"]))
                                if pd.notna(row["programme_id"])
                                else None
                            )
                            print("PROGRAM_ID", program_id)

                            try:
                                program = Program.objects.filter(
                                    program_id=program_id
                                ).first()
                                print("PROGRAM_INSTANCE", program)
                                print("PROGRAMME_NAME", program.programme_name)
                            except Program.DoesNotExist:
                                logger.warning(
                                    f"Row {index + 1}: Program with id {row['programme_id']} does not exist."
                                )
                                skipped_rows.append(
                                    {
                                        "row": index + 1,
                                        "error": f"Program with id {row['programme_id']} does not exist.",
                                    }
                                )
                                continue

                        # Fetch language data
                        try:
                            language = LanguagePage.objects.get(
                                language_id=row["language_id"]
                            )
                        except LanguagePage.DoesNotExist:
                            logger.warning(
                                f"Row {index + 1}: Language with id {row['language_id']} does not exist."
                            )
                            skipped_rows.append(
                                {
                                    "row": index + 1,
                                    "error": f"Language with id {row['language_id']} does not exist.",
                                }
                            )
                            continue

                        iso_language_code = language.iso_language_code.upper()

                        # Generate a unique slug for the ProductUpdate instance
                        slug_update = f"bulkupload-{uuid.uuid4()}"
                        title_update = row["title"]

                        # Create ProductUpdate page using add_child
                        product_update = ProductUpdate(
                            title=title_update,
                            slug=slug_update,
                            minimum_stock_level=row.get("minimum_stock_level"),
                            maximum_order_quantity=row.get("maximum_order_quantity"),
                            quantity_available=row.get("quantity_available", 0),
                            run_to_zero=row.get("run_to_zero", False),
                            available_from_choice=row.get(
                                "available_from_choice", "immediately"
                            ),
                            order_from_date=row.get("order_from_date"),
                            order_end_date=row.get("order_end_date"),
                            product_type=row.get("product_type"),
                            alternative_type=row.get("alternative_type"),
                            cost_centre=row.get("cost_centre", "10200"),
                            local_code=row.get("local_code", "0001"),
                            unit_of_measure=row.get("unit_of_measure"),
                            summary_of_guidance=row.get("summary_of_guidance"),
                            stock_owner_email_address=row.get("stock_owner"),
                            order_referral_email_address=row.get("stock_referral"),
                            product_downloads=row.get("product_downloads", {}),
                        )
                        root_page.add_child(instance=product_update)

                        def fetch_instances_and_names(model, field_name, ids_str):
                            """
                            Given a model and a comma-separated string of IDs,
                            fetch instances and return a list of their names.
                            If ids_str is None or empty, return two empty lists.
                            """
                            if not ids_str:
                                # If ids_str is None or empty, return empty lists for both instances and names
                                return [], []

                            # Split by comma and strip whitespace
                            ids = [
                                id_val.strip()
                                for id_val in ids_str.split(",")
                                if id_val.strip()
                            ]
                            if not ids:
                                # If no valid IDs found after splitting, also return empty lists
                                return [], []

                            instances = model.objects.filter(
                                **{f"{field_name}__in": ids}
                            )
                            # Assuming each model instance has a 'name' attribute
                            names = [inst.name for inst in instances]

                            return list(instances), names

                        # Fetch and assign Many-to-Many relationships and their names
                        audience_instances, audience_names = fetch_instances_and_names(
                            Audience, "audience_id", row.get("audience_id")
                        )
                        product_update.audience_ref.set(audience_instances)

                        (
                            where_to_use_instances,
                            where_to_use_names,
                        ) = fetch_instances_and_names(
                            WhereToUse,
                            "where_to_use_id",
                            row.get("where_to_use_id"),
                        )
                        product_update.where_to_use_ref.set(where_to_use_instances)

                        (
                            vaccination_instances,
                            vaccination_names,
                        ) = fetch_instances_and_names(
                            Vaccination, "vaccination_id", row.get("vaccination_id")
                        )
                        product_update.vaccination_ref.set(vaccination_instances)

                        disease_instances, disease_names = fetch_instances_and_names(
                            Disease, "disease_id", row.get("disease_id")
                        )

                        print("where_to_use_names", where_to_use_names)
                        print("disease_names", disease_names)
                        print("audience_names", audience_names)
                        print("vaccination_names", vaccination_names)
                        product_update.diseases_ref.set(disease_instances)

                        # Save to persist Many-to-Many relationships
                        product_update.save()
                        created_products += 1

                        # Fetch or clean 'version_date'
                        raw_version_date = row.get("version_date", None)
                        publish_date = None

                        if raw_version_date and raw_version_date != "-":
                            # Try to parse the date if it's in a recognizable format (YYYY-MM-DD)
                            try:
                                if isinstance(raw_version_date, datetime.date):
                                    # Already a datetime.date object
                                    publish_date = raw_version_date
                                else:
                                    # Parse the string in YYYY-MM-DD format
                                    publish_date = datetime.datetime.strptime(
                                        raw_version_date, "%Y-%m-%d"
                                    ).date()
                            except ValueError:
                                # If it doesn't match the expected format, set it to None or skip this row
                                logger.warning(
                                    f"Invalid publish_date format for row {index+1}: {raw_version_date}"
                                )
                                publish_date = None

                        # Prepare Product instance
                        slug = f"{slugify(row['title'])}-{row['product_id']}-{uuid.uuid4()}"
                        product = Product(
                            title=row["title"],
                            slug=slug,
                            product_id=row["product_id"],
                            program_name=program.programme_name if program else "",
                            product_title=row["title"],
                            status=row["status"],
                            product_code=row["product_code"],
                            file_url=row["gov_related_article"],
                            tag=row["tag"],
                            product_key=1,
                            program_id=program,
                            language_id=language,
                            version_number="001",
                            iso_language_code=iso_language_code,
                            language_name=row["language_name"],
                            update_ref=product_update,
                            created_at=created_date,
                            is_latest=True,
                            publish_date=publish_date,
                        )
                        logger.info("Product created: %s", product)
                        root_page.add_child(instance=product)
                        created_products += 1

                        # Example final JSON structure (as per your provided example)
                        response_data = {
                            "maximum_order_quantity": product_update.maximum_order_quantity,
                            "run_to_zero": product_update.run_to_zero,
                            "stock_owner_email_address": product_update.stock_owner_email_address,
                            "order_referral_email_address": product_update.order_referral_email_address,
                            "minimum_stock_level": product_update.minimum_stock_level,
                            "unit_of_measure": product_update.unit_of_measure,
                            "available_from_choice": product_update.available_from_choice,
                            "order_from_date": (
                                product_update.order_from_date.isoformat()
                                if product_update.order_from_date
                                else None
                            ),
                            "alternative_type": product_update.alternative_type,
                            "local_code": product_update.local_code,
                            "order_end_date": (
                                product_update.order_end_date.isoformat()
                                if product_update.order_end_date
                                else None
                            ),
                            "cost_centre": product_update.cost_centre,
                            "summary_of_guidance": product_update.summary_of_guidance,
                            "audience_names": audience_names,
                            "vaccination_names": vaccination_names,
                            "disease_names": disease_names,
                            "where_to_use_names": where_to_use_names,
                            "product_type": product_update.product_type,
                            "product_downloads": product_update.product_downloads,
                        }

                        logger.info(
                            "Final response data for product_id %s: %s",
                            product.product_id,
                            response_data,
                        )

                    except (
                        Program.DoesNotExist,
                        LanguagePage.DoesNotExist,
                        ValueError,
                    ) as ve:
                        logger.warning(f"Data error in row {index + 1}: {ve}")
                        skipped_rows.append({"row": index + 1, "error": str(ve)})
                    except Exception as e:
                        logger.exception(f"Unexpected error in row {index + 1}: {e}")
                        skipped_rows.append(
                            {"row": index + 1, "error": f"Unexpected error: {str(e)}"}
                        )

                logger.info(f"Bulk upload completed with {len(skipped_rows)} errors.")

                return Response(
                    {
                        "message": "Bulk upload completed.",
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

    def clean_row_data(self, row):
        """
        Cleans and processes row data. Handles both single and comma-separated numeric fields.
        """

        def clean_numeric_field(value):
            """
            Cleans a numeric field by converting to integer or handling comma-separated lists.
            """
            if pd.notna(value):
                try:
                    if isinstance(value, str) and "," in value:
                        # Handle comma-separated lists
                        return ",".join(
                            (
                                str(int(float(item.strip())))
                                if item.strip().replace(".", "", 1).isdigit()
                                else item.strip()
                            )
                            for item in value.split(",")
                        )
                    elif isinstance(value, (float, int)):
                        # Single numeric value
                        return str(int(float(value)))
                    elif (
                        isinstance(value, str)
                        and value.strip().replace(".", "", 1).isdigit()
                    ):
                        # String representing a numeric value
                        return str(int(float(value.strip())))
                except ValueError:
                    return None
            return None

        row["product_id"] = clean_numeric_field(row.get("product_id"))
        row["unit_of_measure"] = clean_numeric_field(row.get("unit_of_measure"))
        row["programme_id"] = clean_numeric_field(row.get("programme_id"))
        row["language_id"] = clean_numeric_field(row.get("language_id"))
        row["audience_id"] = clean_numeric_field(row.get("audience_id"))
        row["where_to_use_id"] = clean_numeric_field(row.get("where_to_use_id"))
        row["vaccination_id"] = clean_numeric_field(row.get("vaccination_id"))
        row["disease_id"] = clean_numeric_field(row.get("disease_id"))

        return row

    def convert_created_date(self, created_date_str):
        """
        Converts the 'created' field to a datetime object.
        """
        if isinstance(created_date_str, pd.Timestamp):
            return created_date_str.to_pydatetime()
        elif isinstance(created_date_str, str):
            return datetime.datetime.strptime(created_date_str, "%d/%m/%Y %H:%M:%S")
        else:
            raise ValueError(
                f"Unsupported type for 'created': {type(created_date_str)}"
            )

    def get_or_create_root_page(self):
        """
        Ensures the root page for products exists. Creates it if missing.
        """
        try:
            root_page = Page.objects.get(slug="products-root")
            logger.info("Root page 'products-root' found.")
        except Page.DoesNotExist:
            logger.warning("Root page 'products-root' not found. Creating it.")
            try:
                wagtail_root = Page.objects.filter(depth=1).first()
                if not wagtail_root:
                    raise Exception(
                        "Wagtail root page not found. Ensure Wagtail is properly set up."
                    )

                # Create the root page as a ProductUpdate instance
                root_page = ProductUpdate(title="Products Root", slug="products-root")
                wagtail_root.add_child(instance=root_page)  # Establish hierarchy
                logger.info("Root page 'products-root' created successfully.")
            except Exception as ex:
                logger.error("Failed to create root page: %s", str(ex))
                raise
        return root_page


@method_decorator(cache_page(60 * 15), name="dispatch")
class ProductAdminListView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def get(self, request, *args, **kwargs):
        logger.info("ProductAdminListView GET method called")
        try:
            products = Product.objects.filter()
            # for debugging
            # logger.info("Number of products retrieved: %d", products.count())

            if not products.exists():
                logger.warning(ErrorMessage.PRODUCT_NOT_FOUND)
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            # --- Optional: Apply sorting if 'sort_by' parameter is provided ---
            sort_by = request.GET.get("sort_by")
            if sort_by:
                valid_sort_fields = [
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
                if sort_by in valid_sort_fields:
                    products = products.order_by(sort_by)
                else:
                    logger.warning("Invalid sort_by parameter provided: %s", sort_by)

            paginator = CustomPagination()
            paginated_products = paginator.paginate_queryset(products, request)
            # for debugging
            # logger.info("Number of paginated products: %d", len(paginated_products))

            # Serialize the paginated products
            serializer = ProductSerializer(paginated_products, many=True)

            # Extract S3 URLs for presigned URL generation
            all_download_urls = extract_s3_urls(serializer.data)

            # Generate presigned URLs in a batch process
            presigned_urls = generate_presigned_urls(all_download_urls)

            # Update product URLs with the new presigned URLs
            update_product_urls(serializer.data, presigned_urls)

            logger.info(
                "Returning paginated response with %d products", len(serializer.data)
            )
            return paginator.get_paginated_response(
                serializer.data, status_code=status.HTTP_200_OK
            )

        except (DatabaseError, TimeoutError, Exception) as e:
            return handle_exceptions(e)


@method_decorator(cache_page(60 * 15), name="dispatch")
class ProductUsersListView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        logger.info("ProductUsersListView GET method called")
        try:
            # Get only published products where `is_latest` is True and status is 'live'
            # products = Product.objects.filter(is_latest=True, status="live")
            products = Product.objects.filter(status="live")

            if not products.exists():
                logger.warning("No published products found.")
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=status.HTTP_404_NOT_FOUND,
                )

            # --- Optional: Apply sorting if 'sort_by' parameter is provided ---
            sort_by = request.GET.get("sort_by")
            if sort_by:
                valid_sort_fields = [
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
                if sort_by in valid_sort_fields:
                    products = products.order_by(sort_by)
                else:
                    logger.warning("Invalid sort_by parameter provided: %s", sort_by)

            # Initialize custom pagination
            paginator = CustomPagination()
            paginated_products = paginator.paginate_queryset(products, request)
            serializer = ProductSerializer(paginated_products, many=True)

            # Extract S3 URLs for presigned URL generation
            all_download_urls = extract_s3_urls(serializer.data)

            # Generate presigned URLs in a batch process
            presigned_urls = generate_presigned_urls(all_download_urls)

            # Update product URLs with the new presigned URLs
            update_product_urls(serializer.data, presigned_urls)

            # Filter out languages where the product status is not 'live'
            filtered_data = self.filter_languages(serializer.data)

            logger.info(
                "Returning paginated response with %d products", len(filtered_data)
            )
            return paginator.get_paginated_response(
                filtered_data, status_code=status.HTTP_200_OK
            )

        except (DatabaseError, TimeoutError, Exception) as e:
            return handle_exceptions(e)

    def filter_languages(self, products_data):
        """Filter out languages where the product status is not 'live'."""
        filtered_data = []
        for product in products_data:
            existing_languages = product.get("existing_languages", [])
            filtered_languages = [
                lang
                for lang in existing_languages
                if Product.objects.filter(
                    product_code=lang["product_url"].split("/")[-1], status="live"
                ).exists()
            ]
            product["existing_languages"] = filtered_languages
            filtered_data.append(product)
        return filtered_data


class ProductDetailView(View):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, product_code, *args, **kwargs):
        product_code = unquote(product_code)
        logger.info(f"Fetching details for product with product_code: {product_code}")

        try:
            product = Product.objects.filter(product_code=product_code).first()

            if not product:
                logger.warning(f"No product found with product_code: {product_code}")
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=HTTP_404_NOT_FOUND,
                )

            # Fetch the associated product update
            product_update = product.update_ref

            logger.info("Product Update", product_update)

            if product_update is None:
                logger.warning(
                    f"No product update found for product_code: {product.product_code}"
                )
            else:
                logger.info(f"Update Product: {product_update}")

            # Find similar products only for the updates tied to this product
            # Commenting it for now as we would be using it later on
            # similar_products = find_similar_products(product, product_update)

            serializer = ProductSerializer(product)
            response_data = serializer.data
            # response_data["similar_products"] = similar_products

            # Collect all URLs for presigned URL generation
            all_download_urls = []
            update_refs = response_data.get("update_ref") or {}
            if isinstance(update_refs, dict):
                product_downloads = update_refs.get("product_downloads") or {}

                # Check main download URL
                if "main_download_url" in product_downloads:
                    main_download = product_downloads.get("main_download_url") or {}
                    if not isinstance(main_download, dict):
                        main_download = {}
                    if "s3_bucket_url" in main_download:
                        all_download_urls.append(main_download["s3_bucket_url"])

                # Check additional download types
                for download_type in [
                    "web_download_url",
                    "print_download_url",
                    "transcript_url",
                ]:
                    downloads = product_downloads.get(download_type, [])
                    if isinstance(downloads, list):
                        for item in downloads:
                            if isinstance(item, dict) and "s3_bucket_url" in item:
                                all_download_urls.append(item["s3_bucket_url"])

            logger.info(LOG_MSG_S3_URL_EXTRACTION, all_download_urls)

            # Generate new presigned URLs
            presigned_urls = generate_presigned_urls(all_download_urls)
            logger.info("Generated presigned URLs: %s", presigned_urls)

            # Update product download URLs with presigned URLs
            if isinstance(update_refs, dict):
                product_downloads = update_refs.get("product_downloads") or {}

                # Update main_download_url
                if "main_download_url" in product_downloads:
                    main_download = product_downloads.get("main_download_url") or {}
                    s3_url = main_download.get("s3_bucket_url") or ""
                    if s3_url in presigned_urls:
                        main_download["URL"] = presigned_urls[s3_url]

                # Update other download types
                for download_type in [
                    "web_download_url",
                    "print_download_url",
                    "transcript_url",
                ]:
                    downloads = product_downloads.get(download_type, [])
                    if isinstance(downloads, list):
                        for item in downloads:
                            s3_url = item.get("s3_bucket_url", "")
                            if s3_url in presigned_urls:
                                item["URL"] = presigned_urls[s3_url]

            logger.info("Returning product details for product_code: %s", product_code)
            return JsonResponse(response_data, status=200)

        except DatabaseError:
            logger.exception("Database error occurred while fetching product details.")
            return handle_error(
                ErrorCode.DATABASE_ERROR, ErrorMessage.DATABASE_ERROR, status_code=500
            )
        except TimeoutError:
            logger.exception("Timeout error occurred while fetching product details.")
            return handle_error(
                ErrorCode.TIMEOUT_ERROR, ErrorMessage.TIMEOUT_ERROR, status_code=504
            )
        except Exception:
            logger.exception(
                f"An unexpected error occurred while fetching the product details for product_code: {product_code}"
            )
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=500,
            )


class ProductDetailDelete(View):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def delete(self, request, product_code, *args, **kwargs):
        decoded_product_code = unquote(product_code)
        logger.info(
            f"Attempting to delete product with product_code: {decoded_product_code}"
        )
        try:
            product = Product.objects.filter(
                product_code__startswith=decoded_product_code
            ).first()

            if not product:
                logger.warning(
                    f"No product found with product_code: {decoded_product_code}"
                )
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=HTTP_404_NOT_FOUND,
                )

            # Allow withdrawal from either 'draft' or 'live' or'archived status
            if product.status not in ["draft", "live", "archived"]:
                logger.warning(
                    f"Cannot withdraw product {decoded_product_code} as it is not in draft or live or archived status."
                )
                return handle_error(
                    ErrorCode.INVALID_DATA,
                    ErrorMessage.INVALID_DATA,
                    status_code=HTTP_403_FORBIDDEN,
                )

            # Change product status to 'withdrawn' instead of deleting it
            product.status = "withdrawn"
            product.save()
            # for debugging
            # logger.info(
            #     f"Product with product_code {decoded_product_code} archived successfully."
            # )
            return JsonResponse(
                {"message": "Product archived successfully."},
                status=HTTP_204_NO_CONTENT,
            )

        except DatabaseError:
            logger.exception("Database error occurred while archiving product.")
            return handle_error(
                ErrorCode.DATABASE_ERROR,
                ErrorMessage.DATABASE_ERROR,
                status_code=500,
            )
        except TimeoutError:
            logger.exception("Timeout error occurred while archiving product.")
            return handle_error(
                ErrorCode.TIMEOUT_ERROR,
                ErrorMessage.TIMEOUT_ERROR,
                status_code=504,
            )
        except Exception:
            logger.exception(
                f"An unexpected error occurred while archiving the product with product_code: {decoded_product_code}"
            )
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=500,
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
                status=204,  # HTTP_204_NO_CONTENT
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

        if product_code and not re.match(PRODUCT_CODE_PATTERN, product_code):
            return _handle_invalid_query_param()

        try:
            product = get_product(decoded_product_code)
            if not product:
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status_code=HTTP_404_NOT_FOUND,
                )

            new_status = self.get_status_from_request(request)
            if not self.is_valid_status(new_status):
                return handle_error(
                    ErrorCode.INVALID_STATUS,
                    ErrorMessage.INVALID_STATUS,
                    status_code=HTTP_400_BAD_REQUEST,
                )

            if self.is_invalid_status_transition(product.status, new_status):
                return handle_error(
                    ErrorCode.INVALID_TRANSITION,
                    ErrorMessage.INVALID_TRANSITION,
                    status_code=HTTP_400_BAD_REQUEST,
                )

            if new_status == "live":
                missing_fields = self.check_required_fields(product)
                if missing_fields:
                    return JsonResponse(
                        {
                            "error": "Cannot change status to 'live' due to missing fields.",
                            "missing_fields": missing_fields,
                        },
                        status=HTTP_400_BAD_REQUEST,
                    )
                if not product.publish_date:
                    product.publish_date = timezone.now()

            product.status = new_status
            product.save()
            logger.info(
                f"Product status updated to {new_status} for product_code: {decoded_product_code}"
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

    def is_invalid_status_transition(
        self, current_status: str, new_status: str
    ) -> bool:
        """
        Check if the status transition is invalid based on the allowed transitions.
        """
        allowed_next_statuses = self.ALLOWED_TRANSITIONS.get(current_status, [])
        return new_status not in allowed_next_statuses

    def get_status_from_request(self, request) -> str:
        """Extract the new status from the request body."""
        data = json.loads(request.body)
        return data.get("status")

    def is_valid_status(self, status: str) -> bool:
        """Check if the provided status is valid."""
        valid_statuses = [
            choice[0] for choice in Product._meta.get_field("status").choices or []
        ]
        return status in valid_statuses

    def check_required_fields(self, product: Product) -> list:
        """
        Check for missing required fields in the Product and ProductUpdateSerializer.

        Args:
            product (Product): The product instance to check.

        Returns:
            list: A list of missing required fields.
        """

        missing_fields = []

        # Fields to check in Product
        required_product_fields = [
            "product_title",
            "language_id",
            "program_id",
            "update_ref",
        ]
        missing_fields.extend(
            [field for field in required_product_fields if not getattr(product, field)]
        )

        # If update_ref is None, check required fields in ProductUpdateSerializer
        if product.update_ref is None:
            product_update_serializer = ProductUpdateSerializer()
            # Assuming that `ProductUpdateSerializer` fields are required by default
            for field in product_update_serializer.fields:
                logging.info("product_update", product_update_serializer.fields[field])
                if product_update_serializer.fields[field].required:
                    missing_fields.append(field)

        elif product.update_ref is not None:
            product_update_serializer = ProductUpdateSerializer(product.update_ref)
            for field, field_value in product_update_serializer.data.items():
                if (
                    field_value in [None, "", [], {}]
                    and field in product_update_serializer.fields
                ):
                    if product_update_serializer.fields[field].required:
                        missing_fields.append(field)

        return missing_fields


class ProductSearchAdminView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    pagination_class = CustomPagination

    def get(self, request, *args, **kwargs):
        try:
            # Extract and validate query parameters
            product_code = request.GET.get("product_code")
            product_title = request.GET.get("product_title")

            if product_code and not re.match(PRODUCT_CODE_PATTERN, product_code):
                return _handle_invalid_query_param()

            if product_title and not isinstance(product_title, str):
                return _handle_invalid_query_param()

            # Build the query
            query = Q()
            if product_code:
                query &= Q(product_code_no_dashes__icontains=product_code)
            if product_title:
                query &= Q(product_title__icontains=product_title)

            # Fetch matching products
            products = Product.objects.filter(query)
            if not products.exists():
                return Response(
                    {"detail": ErrorMessage.PRODUCT_NOT_FOUND},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # --- Apply sorting based on sort_by parameter ---
            sort_by = request.GET.get("sort_by", "product_title")
            valid_sort_fields = [
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

            if sort_by in valid_sort_fields:
                products = products.order_by(sort_by)
            else:
                products = products.order_by("product_title")

            # Apply pagination
            paginator = self.pagination_class()
            paginated_products = paginator.paginate_queryset(products, request)

            # Serialize product information
            serializer = ProductSerializer(paginated_products, many=True)

            # Prepare the response data
            response_data = _prepare_response_data(
                products, serializer, product_code, product_title
            )

            # Generate presigned URLs for all downloadable product references
            all_download_urls = _collect_download_urls(products)
            logger.info(LOG_MSG_S3_URL_EXTRACTION, all_download_urls)

            # Generate new presigned URLs
            presigned_urls = generate_presigned_urls(all_download_urls)
            logger.info("Generated presigned URLs: %s", presigned_urls)

            # Update product download URLs with presigned URLs
            self._update_product_download_urls(paginated_products, presigned_urls)

            # Get recommended products based on the search results
            recommended_products = get_recommended_products(products)
            response_data["recommended_products"] = recommended_products

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

    def _update_product_download_urls(self, product_data, presigned_urls):
        """Update product download URLs with presigned URLs."""
        for product in product_data:
            logger.info("Updating Product: %s", product.product_id)

            # Fetch the product from the database
            product_instance = Product.objects.filter(
                product_id=product.product_id
            ).first()

            if (
                product_instance and product_instance.update_ref
            ):  # Ensure update_ref is not None
                update_refs = product_instance.update_ref
                product_downloads = update_refs.product_downloads  # Access directly

                # Update main_download_url
                if "main_download_url" in product_downloads:
                    # Access directly
                    main_download = product_downloads["main_download_url"]
                    s3_url = main_download["s3_bucket_url"]  # Access directly
                    logger.info("Original main_download_url: %s", s3_url)

                    # Always replace with new presigned URL if exists
                    if s3_url in presigned_urls:
                        new_url = presigned_urls[s3_url]
                        logger.info("Replacing with new presigned URL: %s", new_url)
                        main_download["URL"] = new_url
                        # Save the update back to the database
                        update_refs.save()

                # Update other download types
                for download_type in [
                    "web_download_url",
                    "print_download_url",
                    "transcript_url",
                ]:
                    if download_type in product_downloads:
                        # Access directly
                        downloads = product_downloads[download_type]
                        if isinstance(downloads, list):
                            for item in downloads:
                                # Access directly
                                s3_url = item["s3_bucket_url"]
                                logger.info("Original %s: %s", download_type, s3_url)

                                # Always attempt to replace with new presigned URL
                                if s3_url in presigned_urls:
                                    new_url = presigned_urls[s3_url]
                                    logger.info(
                                        "Replacing %s with new presigned URL: %s",
                                        download_type,
                                        new_url,
                                    )
                                    item["URL"] = new_url
                                else:
                                    logger.info(
                                        "No replacement found for %s: %s",
                                        download_type,
                                        s3_url,
                                    )

                # Save the changes to the product downloads back to the database
                update_refs.save()
            else:
                logger.warning(
                    "No product_instance or update_ref found for product_id: %s",
                    product.product_id,
                )


class ProductSearchUserView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    pagination_class = CustomPagination

    def get(self, request, *args, **kwargs):
        try:
            # Extract and validate query parameters
            product_code = request.GET.get("product_code")
            product_title = request.GET.get("product_title")

            if product_code and not re.match(PRODUCT_CODE_PATTERN, product_code):
                return _handle_invalid_query_param()

            if product_title and not isinstance(product_title, str):
                return _handle_invalid_query_param()

            # Build the query
            query = Q(is_latest=True, status="live")
            if product_code:
                query &= Q(product_code_no_dashes__icontains=product_code)
            if product_title:
                query &= Q(product_title__icontains=product_title)

            # Fetch matching products
            products = Product.objects.filter(query)
            if not products.exists():
                return Response(
                    {"detail": str(ErrorMessage.PRODUCT_NOT_FOUND)},
                    status=status.HTTP_404_NOT_FOUND,
                )
            # --- Apply sorting based on sort_by parameter ---
            sort_by = request.GET.get("sort_by", "product_title")
            valid_sort_fields = [
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
            if sort_by in valid_sort_fields:
                products = products.order_by(sort_by)
            else:
                products = products.order_by("product_title")

            # Apply pagination
            paginator = self.pagination_class()
            paginated_products = paginator.paginate_queryset(products, request)

            # Collect all URLs for presigned URL generation
            all_download_urls = _collect_download_urls(paginated_products)
            logger.info(LOG_MSG_S3_URL_EXTRACTION, all_download_urls)

            # Generate new presigned URLs
            presigned_urls = generate_presigned_urls(all_download_urls)
            logger.info("Generated presigned URLs: %s", presigned_urls)

            # Update product download URLs with new presigned URLs
            _update_product_downloads_with_presigned_urls(
                paginated_products, presigned_urls
            )

            # Re-serialize the updated products after URL updates
            updated_serializer = ProductSerializer(paginated_products, many=True)

            # Prepare response data
            response_data = _prepare_response_data(
                products, updated_serializer, product_code, product_title
            )

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


class UsersProductFilterView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    pagination_class = CustomPagination

    def get(self, request, *args, **kwargs) -> Response:
        """
        Retrieve filtered products based on query parameters.
        Args:
            request (HttpRequest): The HTTP request object containing query parameters.
        Returns:
            Response: A JSON response containing the filtered products.
        """
        try:
            # Extract query parameters
            recently_updated = request.GET.get("recently_updated", None)
            download_or_order = request.GET.get("download_or_order", None)
            download_only = request.GET.get("download_only", None)
            order_only = request.GET.get("order_only", None)
            audience_names = request.GET.getlist("audiences", [])
            program_names = request.GET.getlist("program_names", [])
            disease_names = request.GET.getlist("diseases", [])
            vaccination_names = request.GET.getlist("vaccinations", [])
            product_types = request.GET.getlist("product_type", [])
            language_names = request.GET.getlist("languages", [])
            alternative_type = request.GET.getlist("alternative_type", [])
            where_to_use_names = request.GET.getlist("where_to_use", [])
            sort_by = request.GET.get("sort_by", "product_title")

            # Build the query
            query = Q()

            # Apply filters to the query
            if recently_updated:
                try:
                    query &= Q(updated_at__gte=recently_updated)
                except ValueError:
                    return _handle_invalid_query_param()

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

            # Fetch matching products where is_latest=True and status='live'
            products = Product.objects.filter(query, is_latest=True, status="live")

            # Sort the products
            valid_sort_fields = [
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
            if sort_by in valid_sort_fields:
                products = products.order_by(sort_by)
            else:
                products = products.order_by("product_title")

            # Apply pagination
            paginator = self.pagination_class()
            paginated_products = paginator.paginate_queryset(products, request)

            # Collect all URLs for presigned URL generation
            all_download_urls = _collect_download_urls(paginated_products)
            logger.info(
                "Extracted download URLs for presigned URL generation: %s",
                all_download_urls,
            )

            # Generate new presigned URLs
            presigned_urls = generate_presigned_urls(all_download_urls)
            logger.info("Generated presigned URLs: %s", presigned_urls)

            # Update product download URLs with presigned URLs
            _update_product_downloads_with_presigned_urls(
                paginated_products, presigned_urls
            )

            # Serialize the products
            serializer = ProductSerializer(paginated_products, many=True)

            # Filter out languages from `existing_languages` where the product status is not 'live'
            filtered_data = []
            for product in serializer.data:
                existing_languages = product.get("existing_languages", [])
                filtered_languages = [
                    lang
                    for lang in existing_languages
                    if Product.objects.filter(
                        product_code=lang["product_url"].split("/")[-1], status="live"
                    ).exists()
                ]
                product["existing_languages"] = filtered_languages
                filtered_data.append(product)

            return paginator.get_paginated_response(filtered_data)

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


class AdminProductFilterView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    pagination_class = CustomPagination

    def get(self, request, *args, **kwargs) -> Response:
        """
        Retrieve filtered products based on admin query parameters.
        """
        try:
            # Extract query parameters
            access_type = request.GET.getlist("access_type", [])
            status_filter = request.GET.getlist("status", [])
            sort_by = request.GET.get("sort_by", "product_title")
            product_code = request.GET.get("product_code", None)
            disease_names = request.GET.getlist("diseases", [])
            vaccination_names = request.GET.getlist("vaccinations", [])
            audience_names = request.GET.getlist("audiences", [])
            language_names = request.GET.getlist("languages", [])
            alternative_type = request.GET.getlist("alternative_type", [])
            where_to_use_names = request.GET.getlist("where_to_use", [])
            product_types = request.GET.getlist("product_type", [])

            # Build the query
            query = Q()
            if disease_names:
                query &= Q(update_ref__diseases_ref__name__in=disease_names)
            if vaccination_names:
                query &= Q(update_ref__vaccination_ref__name__in=vaccination_names)
            if audience_names:
                query &= Q(update_ref__audience_ref__name__in=audience_names)
            if where_to_use_names:
                query &= Q(update_ref__where_to_use_ref__name__in=where_to_use_names)
            if alternative_type:
                query &= Q(update_ref__alternative_type__in=alternative_type)
            if product_types:
                query &= Q(update_ref__product_type__in=product_types)
            if language_names:
                query &= Q(language_name__in=language_names)
            if access_type:
                query &= Q(tag__in=access_type)
            if status_filter:
                query &= Q(status__in=status_filter)
            if product_code:
                query &= Q(product_code_no_dashes__icontains=product_code)

            # Fetch matching products
            products = Product.objects.filter(query)

            # Sort the products
            valid_sort_fields = [
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
            products = (
                products.order_by(sort_by)
                if sort_by in valid_sort_fields
                else products.order_by("product_title")
            )

            # Apply pagination
            paginator = self.pagination_class()
            paginated_products = paginator.paginate_queryset(products, request)

            # Collect all URLs for presigned URL generation
            all_download_urls = _collect_download_urls(products)
            logger.info(
                "Extracted download URLs for presigned URL generation: %s",
                all_download_urls,
            )

            # Generate new presigned URLs
            presigned_urls = generate_presigned_urls(all_download_urls)
            logger.info("Generated presigned URLs: %s", presigned_urls)

            # Update product download URLs with presigned URLs
            _update_product_downloads_with_presigned_urls(
                paginated_products, presigned_urls
            )

            # Serialize the data
            updated_serializer = ProductSerializer(paginated_products, many=True)

            return paginator.get_paginated_response(updated_serializer.data)

        except DatabaseError:
            return _handle_database_error()
        except ValidationError:
            return _handle_invalid_query_param()
        except Exception:
            logger.exception(INTERNAL_ERROR_MSG)
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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

    def handle_error(
        self, error_code: str, error_message: str, status_code: int
    ) -> JsonResponse:
        """
        Handle errors by returning a JSON response with the given error code, message, and status code.

        Args:
            error_code (str): The error code representing the type of error.
            error_message (str): A message describing the error.
            status_code (int): The HTTP status code to be returned.

        Returns:
            JsonResponse: A JSON response with the error details.
        """
        return JsonResponse(
            {"error_code": error_code, "error_message": error_message},
            status=status_code,
        )


class ProductPatchView(View):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    """
    View to handle product updates via PATCH requests.
    """

    def patch(self, request, product_code, *args, **kwargs) -> JsonResponse:
        """
        Update a product with the given product_code.

        Args:
            request (HttpRequest): The HTTP request containing update data.
            product_code (str): The product code to identify the product to be updated.

        Returns:
            JsonResponse: A response containing the result of the update operation.
        """
        decoded_product_code = unquote(product_code)
        logger.info(f"Updating product with product_code: {decoded_product_code}")

        try:
            product = get_product(decoded_product_code)
            if not product:
                logger.warning(
                    f"No product found with product_code: {decoded_product_code}"
                )
                return handle_error(
                    ErrorCode.PRODUCT_NOT_FOUND,
                    ErrorMessage.PRODUCT_NOT_FOUND,
                    status.HTTP_404_NOT_FOUND,
                )
            data = json.loads(request.body)
            product_type = data.get("product_type")
            product_downloads = data.get("product_downloads", {})

            self.validate_required_downloads(product_type, product_downloads)
            file_urls = self.process_file_urls(product_type, product_downloads)

            available_from_choice = data.get("available_from_choice")
            order_from_date = data.get("order_from_date")

            if available_from_choice == "specific_date" and not order_from_date:
                logger.error(
                    "order_from_date must be provided when available_from_choice is 'specific_date'."
                )

                return handle_error(
                    ErrorCode.MISSING_ORDER_FROM_DATE,
                    ErrorMessage.MISSING_ORDER_FROM_DATE,
                    status_code=400,
                )
            product_update_data = self.prepare_product_update_data(
                data, available_from_choice, order_from_date, file_urls
            )

            with transaction.atomic():
                # Update order limits if present
                order_limits = data.get("order_limits")
                if order_limits:
                    self.update_order_limits(product, order_limits)

                # Update the product and handle foreign keys
                serializer = ProductSerializer(product, data=data, partial=True)
                if serializer.is_valid():
                    updated_product = serializer.save()
                    if updated_product.update_ref:
                        self.update_foreign_keys(updated_product.update_ref, data)

                    # Update or create ProductUpdate instance
                    self.get_or_create_product_update(product, product_update_data)

                    response_data = serializer.data
                    if updated_product.update_ref:
                        response_data["update_ref"] = ProductUpdateSerializer(
                            updated_product.update_ref
                        ).data

                    logger.info(
                        f"Product updated successfully with new data for product_code: {decoded_product_code}"
                    )

                    return JsonResponse(response_data, status=status.HTTP_200_OK)
                else:
                    logger.error(
                        f"Serializer errors during product update: {serializer.errors}"
                    )
                    return handle_error(
                        ErrorCode.INVALID_DATA,
                        ErrorMessage.INVALID_DATA,
                        status_code=400,
                    )

        except ValidationError as e:
            logger.error(f"Validation error: {str(e)}")
            return handle_error(
                ErrorCode.INVALID_DATA,
                ErrorMessage.INVALID_DATA,
                status_code=400,
            )
        except DatabaseError as e:
            logger.exception(f"Database error occurred: {str(e)}")
            return handle_error(
                ErrorCode.DATABASE_ERROR,
                ErrorMessage.DATABASE_ERROR,
                status_code=500,
            )
        except AttributeError as e:
            logger.error(f"Attribute error: {str(e)}")
            return handle_error(
                ErrorCode.ATTRIBUTE_ERROR,
                ErrorMessage.ATTRIBUTE_ERROR,
                status_code=400,
            )
        except Exception as e:
            logger.exception(f"Unexpected error: {str(e)}")
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=500,
            )

    def process_file_urls(self, product_type: str, product_downloads: dict) -> dict:
        """Process file URLs for the product based on the product type and downloads."""
        self.validate_required_downloads(product_type, product_downloads)
        file_urls = self.initialize_file_urls(product_downloads)
        file_urls = self.validate_file_extensions(file_urls)
        file_urls = self.add_file_metadata(file_urls)
        return file_urls

    def validate_required_downloads(self, product_type: str, product_downloads: dict):
        """Validate if required downloads are present for the product type."""
        required_downloads = {
            "Audio": ["main_download", "web_download", "transcript"],
            "Bulletins": ["main_download", "print_download", "web_download"],
            # Other product types...
        }

        if product_type in required_downloads:
            missing_downloads = [
                d
                for d in required_downloads[product_type]
                if d not in product_downloads
            ]
            if missing_downloads:
                raise ValidationError(
                    f"Missing required downloads for {product_type} product type. Expected: {', '.join(missing_downloads)}."
                )

    def initialize_file_urls(self, product_downloads: dict) -> dict:
        """Initialize file URLs based on provided downloads."""
        return {
            "main_download_url": product_downloads.get("main_download", ""),
            "web_download_url": product_downloads.get("web_download", []),
            "print_download_url": product_downloads.get("print_download", []),
            "transcript_url": product_downloads.get("transcript", []),
            "video_url": product_downloads.get("video_url", ""),
        }

    def validate_file_extensions(self, file_urls: dict) -> dict:
        """Validate the file URLs against allowed extensions."""
        allowed_extensions = {
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

        # Validate single main_download_url
        if file_urls["main_download_url"]:
            main_download_extension = file_urls["main_download_url"].split(".")[-1]
            if main_download_extension not in allowed_extensions["main_download_url"]:
                file_urls["main_download_url"] = ""  # Clear if invalid

        # Validate lists for other file types
        for key in ["web_download_url", "print_download_url", "transcript_url"]:
            file_urls[key] = [
                url
                for url in file_urls[key]
                if url.split(".")[-1] in allowed_extensions.get(key, [])
            ]

        return file_urls

    def add_file_metadata(self, file_urls: dict) -> dict:
        """
        Generate pre-signed URLs for all file URLs, retrieve metadata for those presigned URLs,
        and map it back to the provided file URLs.

        Args:
            file_urls (dict): A dictionary containing file URLs to process.

        Returns:
            dict: Updated file URLs with metadata.
        """
        all_urls = []

        # Handle 'main_download_url' as a single URL (not a list).
        if "main_download_url" in file_urls and file_urls["main_download_url"]:
            all_urls.append(file_urls["main_download_url"])

        # Collect all other URLs from lists (e.g., web_download_url, print_download_url).
        for key, value in file_urls.items():
            if key != "main_download_url" and isinstance(value, list):
                all_urls.extend(value)

        # Generate pre-signed URLs for all URLs first.
        presigned_urls = generate_presigned_urls(all_urls)

        # Get metadata for all presigned URLs.
        metadata_list = get_file_metadata(list(presigned_urls.values()))
        metadata_dict = {metadata["URL"]: metadata for metadata in metadata_list}

        # Map metadata and pre-signed URLs back to file URLs.
        for key, value in file_urls.items():
            # Handle 'main_download_url' as a single item.
            if key == "main_download_url" and value:
                url = value
                presigned_url = presigned_urls.get(url)
                metadata = metadata_dict.get(presigned_url, {"URL": url})
                metadata["s3_bucket_url"] = url
                file_urls[key] = metadata

            # Handle list-based URLs (e.g., web_download_url, print_download_url).
            elif isinstance(value, list):
                updated_list = []
                for url in value:
                    presigned_url = presigned_urls.get(url)
                    metadata = metadata_dict.get(presigned_url, {"URL": url})
                    metadata["s3_bucket_url"] = url
                    updated_list.append(metadata)
                file_urls[key] = updated_list

        return file_urls

    def prepare_product_update_data(
        self,
        data: dict,
        available_from_choice: str,
        order_from_date: str,
        file_urls: dict,
    ) -> dict:
        """Prepare the data for updating or creating a ProductUpdate instance."""
        return {
            "minimum_stock_level": data.get("minimum_stock_level"),
            "maximum_order_quantity": data.get("maximum_order_quantity"),
            "available_from_choice": available_from_choice,
            "order_from_date": (
                order_from_date if available_from_choice == "specific_date" else None
            ),
            "order_end_date": data.get("order_end_date"),
            "product_type": data.get("product_type"),
            "alternative_type": data.get("alternative_type"),
            "run_to_zero": data.get("run_to_zero"),
            "cost_centre": data.get("cost_centre"),
            "local_code": data.get("local_code"),
            "unit_of_measure": data.get("unit_of_measure"),
            "order_exceptions": data.get("order_exceptions"),
            "summary_of_guidance": data.get("summary_of_guidance"),
            "order_referral_email_address": data.get(
                "order_referral_email_address", ""
            ),
            "stock_owner_email_address": data.get("stock_owner_email_address"),
            "product_downloads": file_urls,
            "title": "Product_Update Title",
            "slug": slugify("product-update" + str(datetime.datetime.now())),
        }

    def get_or_create_product_update(
        self, product: Product, product_update_data: dict
    ) -> ProductUpdate:
        """Fetch or create a ProductUpdate instance and save it."""
        product_update = product.update_ref
        if not product_update:
            logger.info("Creating a new ProductUpdate instance.")
            parent_page = product.get_parent()
            product_update = ProductUpdate(**product_update_data)
            parent_page.add_child(instance=product_update)
            product_update.save_revision().publish()
            product.update_ref = product_update
        else:
            logger.info("Updating existing ProductUpdate instance.")
            for key, value in product_update_data.items():
                setattr(product_update, key, value)
        product_update.save()
        product.save()
        return product_update

    def update_order_limits(self, product: Product, order_limits: list):
        """Update order limits associated with the product."""
        OrderLimitPage.objects.filter(product_ref=product).delete()

        for limit in order_limits:
            organization_name = limit.get("organization_name")
            if organization_name:
                order_limit_value = limit.get("order_limit_value", 0)
                organization_instance = get_object_or_404(
                    Organization, name=organization_name
                )

                # Fetch full_external_keys from the Establishment table
                full_external_keys = list(
                    Establishment.objects.filter(
                        organization_ref=organization_instance
                    ).values_list("full_external_key", flat=True)
                )

                order_limit_page = OrderLimitPage(
                    title=f"Order Limit for {organization_name}",
                    slug=slugify(
                        f"{organization_name}-order-limit-{datetime.datetime.now()}"
                    ),
                    order_limit=order_limit_value,
                    product_ref=product,
                    organization_ref=organization_instance,
                    full_external_keys=full_external_keys,
                )
                parent_page = Page.objects.get(slug="products")
                parent_page.add_child(instance=order_limit_page)
                order_limit_page.save()

    def update_foreign_keys(self, product_update: ProductUpdate, data: dict):
        """Update foreign key relationships for the product update."""
        for field_name, model_class, relationship_field in [
            ("audience_names", Audience, "audience_ref"),
            ("vaccination_names", Vaccination, "vaccination_ref"),
            ("disease_names", Disease, "diseases_ref"),
            ("where_to_use_names", WhereToUse, "where_to_use_ref"),
        ]:
            self.update_many_to_many_relationships(
                product_update, data, field_name, model_class, relationship_field
            )
        product_update.save()

    def update_many_to_many_relationships(
        self,
        product_update: ProductUpdate,
        data: dict,
        field_name: str,
        model_class,
        relationship_field: str,
    ):
        """Helper function to update many-to-many relationships."""
        names = data.get(field_name, [])
        refs = []
        for name in names:
            try:
                ref = model_class.objects.get(name=name)
                refs.append(ref)
            except model_class.DoesNotExist:
                logger.warning(f"{model_class.__name__} with name {name} not found.")
        if hasattr(product_update, relationship_field):
            getattr(product_update, relationship_field).set(refs)
            if not refs:
                getattr(product_update, relationship_field).clear()
        else:
            logger.error(f"ProductUpdate does not have attribute {relationship_field}")


class ProductCreateView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def post(self, request, *args, **kwargs):
        logger.info("ProductCreateView POST method called")

        try:
            data = json.loads(request.body)
            logger.info("Data received: %s", data)

            # Validate required fields
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
                    ErrorCode.MISSING_FIELD,
                    ErrorMessage.MISSING_FIELD,
                    status_code=400,
                )

            product_title = data["product_title"]
            language_id = data["language_id"]
            file_url = data["file_url"]
            program_name = data["program_name"]
            product_id = data.get("product_id")
            tag = data.get("tag")

            # Extract publish_date from the request data, defaulting to None
            publish_date = data.get("publish_date", None)

            # Check if the language_id exists in the LanguagePage table
            if not LanguagePage.objects.filter(language_id=language_id).exists():
                logger.warning(
                    "Language ID %s does not exist in languages table", language_id
                )
                return handle_error(
                    ErrorCode.INVALID_DATA,
                    ErrorMessage.LANGUAGE_ID_DOES_NOT_EXIST,
                    status_code=400,
                )

                # Check if the program_name exists in the Program table

            if not Program.objects.filter(programme_name=program_name).exists():
                logger.warning(
                    "Program name %s does not exist in programs table", program_name
                )
                return handle_error(
                    ErrorCode.INVALID_DATA,
                    ErrorMessage.PROGRAM_NAME_DOES_NOT_EXIST,
                    status_code=400,
                )

            # Determine if language_id is a UUID or plain number
            try:
                # Attempt to parse as UUID
                uuid.UUID(language_id)
                is_uuid = True
            except ValueError:
                is_uuid = False

            # Fetch program and language data
            program, iso_language_code, language_page = self.get_program_and_language(
                program_name, language_id, is_uuid
            )
            if program is None or iso_language_code is None or language_page is None:
                return handle_error(
                    ErrorCode.INVALID_DATA,
                    ErrorMessage.INVALID_PROGRAM_OR_LANGUAGE,
                    status_code=400,
                )

            # Check if the product already exists
            existing_product = Product.objects.filter(
                program_name=program.programme_name,
                product_title__icontains=product_title,
            ).first()

            # Determine product key and version number
            product_key, version_number = self.get_product_key_and_version(
                program, product_title, language_id
            )

            # Mark previous versions as archived
            self.mark_previous_versions_archived(existing_product, language_id)

            # Ensure product code is unique
            product_code = self.generate_unique_product_code(
                program.program_id, product_key, iso_language_code, version_number
            )

            # Update data with validated fields
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

            # Retrieve or create parent page
            parent_page = self.get_or_create_parent_page()

            # Handle user reference
            user_instance = self.get_user_instance(data.get("user_id"))

            # Create and save product instance
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

        except (DatabaseError, TimeoutError) as e:
            logger.exception("Database or timeout error: %s", str(e))
            return handle_error(
                ErrorCode.DATABASE_ERROR,
                ErrorMessage.DATABASE_ERROR,
                status_code=500,
            )
        except ValidationError as e:
            logger.exception("Validation error: %s", str(e))
            return handle_error(
                ErrorCode.INVALID_DATA,
                ErrorMessage.INVALID_DATA,
                status_code=400,
            )
        except Exception as e:
            logger.exception("Unexpected error: %s", str(e))
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=500,
            )

    def get_program_and_language(self, program_name, language_id, is_uuid):
        try:
            program = Program.objects.get(programme_name=program_name)
            if is_uuid:
                language_page = LanguagePage.objects.get(language_id=language_id)
            else:
                # Handle the case where language_id is a plain number
                language_page = LanguagePage.objects.get(language_id__exact=language_id)
            iso_language_code = language_page.iso_language_code.upper()
            logger.info(
                "Program and language found: %s (ISO Code: %s)",
                language_id,
                iso_language_code,
            )
            return program, iso_language_code, language_page
        except ObjectDoesNotExist as e:
            logger.warning("Program or language not found: %s", str(e))
            return None, None

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

        logger.info(f"Product key: {product_key}, Version number: {version_number}")
        return product_key, version_number

    def mark_previous_versions_archived(self, existing_product, language_id):
        if existing_product is not None:
            # Fetch previous versions of this product that are marked as the latest
            previous_versions = Product.objects.filter(
                product_key=existing_product.product_key,
                language_id=language_id,
                is_latest=True,
            )

            logger.info(f"Previous versions found: {previous_versions.count()}")

            # Update all previous versions to "archived"
            for previous_version in previous_versions:
                previous_version.is_latest = False
                previous_version.status = "archived"
                previous_version.save()
                logger.info(
                    f"Marked previous version as archived: {previous_version.product_code}"
                )

        else:
            logger.info("No existing product found. No previous versions to update.")

    def trigger_event_for_archived_product(self, product_instance):
        """
        Trigger an event for an archived product.
        """
        send_product_event(
            product_instance,
            "archived",
            "ProductArchived",
            required_event_fields_archived,
        )

    def generate_unique_product_code_prev(
        self, program_id, product_key, iso_language_code, version_number
    ):
        product_code = (
            f"{program_id}-{product_key}-{iso_language_code}-{version_number:03}"
        )
        while Product.objects.filter(product_code=product_code).exists():
            version_number += 1
            product_code = (
                f"{program_id}-{product_key}-{iso_language_code}-{version_number:03}"
            )
        logger.info("Unique product code generated: %s", product_code)
        return product_code

    def generate_unique_product_code(
        self, program_id, product_key, iso_language_code, version_number
    ):
        # Abbreviate components to fit within 18 characters
        short_program_id = str(program_id)[
            :5
        ]  # Take first 4 characters of program_id / previously 3
        short_product_key = str(product_key)[
            :4
        ]  # Take first 3 characters of product_key
        short_language_code = iso_language_code[
            :4
        ]  # Use 4-character ISO code / previously 2

        # Generate compact product code
        product_code = f"{short_program_id}{short_product_key}{short_language_code}{version_number:03}"  # previously version_number:02

        # Ensure uniqueness
        while Product.objects.filter(product_code=product_code).exists():
            version_number += 1
            product_code = f"{short_program_id}{short_product_key}{short_language_code}{version_number:03}"  # previously version_number:02

        logger.info("Unique product code generated: %s", product_code)
        return product_code

    def get_or_create_parent_page(self):
        try:
            parent_page = Page.objects.get(slug="products")
            logger.info("Parent page 'products' found.")
        except Page.DoesNotExist:
            logger.warning("Parent page 'products' not found, creating new one.")
            try:
                root_page = Page.objects.first()
                parent_page = Page(
                    title="Products",
                    slug="products",
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)
                logger.info("Parent page 'products' created.")
            except Exception as ex:
                logger.error("Failed to create parent page: %s", str(ex))
                raise
        return parent_page

    def get_user_instance(self, user_ref_id):
        if user_ref_id:
            try:
                return User.objects.get(user_id=user_ref_id)
            except User.DoesNotExist as e:
                logger.warning("User with ID %s not found: %s", user_ref_id, str(e))
                handle_error(
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

                # Use add_child to handle depth and path automatically
                parent_page.add_child(instance=product_instance)

                logger.info("Product instance created successfully.")
                return product_instance

            except Exception as ex:
                logger.error("Error creating product instance: %s", str(ex))
                return None
        else:
            logger.error("Serializer errors: %s", serializer.errors)
            handle_error(
                ErrorCode.INVALID_DATA,
                ErrorMessage.INVALID_DATA,
                status_code=400,
            )
            return None


class ProgramProductsView(APIView):
    """
    API view to retrieve products related to a specific program,
    filtered by associated diseases and vaccinations.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def get(self, request, program_id):
        """
        Handle GET requests to retrieve filtered products, diseases, and vaccinations
        related to the specified program.
        """
        try:
            # Fetch the program; return 404 if not found
            program = get_object_or_404(Program, pk=program_id)

            # Retrieve diseases and vaccinations associated with the program
            diseases = Disease.objects.filter(programs=program)
            vaccinations = Vaccination.objects.filter(programs=program)

            # Construct Q objects for diseases and vaccinations
            diseases_q = Q(update_ref__diseases_ref__in=diseases)
            vaccinations_q = Q(update_ref__vaccination_ref__in=vaccinations)

            # Combine Q objects using OR to include products related to either or both
            products = Product.objects.filter(
                Q(program_id=program) & (diseases_q | vaccinations_q)
            ).distinct()

            # Optimize query with prefetch_related if relationships exist
            # Adjust 'update_ref' and related fields based on your actual model relations
            products = products.prefetch_related(
                "update_ref__diseases_ref", "update_ref__vaccination_ref"
            )

            # Initialize custom pagination
            paginator = CustomPagination()
            paginated_products = paginator.paginate_queryset(products, request)

            # Serialize the paginated products
            product_serializer = ProductSerializer(paginated_products, many=True)

            # Extract S3 URLs for presigned URL generation
            all_download_urls = extract_s3_urls(product_serializer.data)

            # Generate presigned URLs in a batch process
            presigned_urls = generate_presigned_urls(all_download_urls)

            # Update product URLs with the new presigned URLs
            update_product_urls(product_serializer.data, presigned_urls)

            # Serialize diseases and vaccinations for frontend filtering
            disease_serializer = DiseaseSerializer(diseases, many=True)
            vaccination_serializer = VaccinationSerializer(vaccinations, many=True)

            # Construct the response data
            response_data = {
                "products": product_serializer.data,
                "diseases": disease_serializer.data,
                "vaccinations": vaccination_serializer.data,
            }

            # Return the paginated response with HTTP 200 status
            return paginator.get_paginated_response(
                response_data, status_code=status.HTTP_200_OK
            )

        except Http404:
            # Handle case where program is not found
            return Response(
                {"detail": "Program not found."}, status=status.HTTP_404_NOT_FOUND
            )
        except Exception as e:
            # Log the exception with stack trace for debugging
            logger.exception(
                "An error occurred while fetching program products: %s", str(e)
            )
            # Return a generic error message to the client
            return Response(
                {"detail": UNEXPECTED_ERROR_MSG},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


#
