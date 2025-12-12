import uuid
import logging
from venv import logger
from core.audiences.serializers import AudienceSerializer
from core.diseases.serializers import DiseaseSerializer
from core.languages.models import LanguagePage
from core.order_limits.serializers import OrderLimitPageSerializer
from core.programs.models import Program
from core.vaccinations.serializers import VaccinationSerializer
from core.where_to_use.serializers import WhereToUseSerializer
from rest_framework import serializers

from .models import Product, ProductUpdate
from .choices import (
    COST_CENTRE_CHOICES,
    LOCAL_CODES_CHOICES,
    PRODUCT_TYPE_CHOICE,
    ALTERNATIVE_TYPE_CHOICE,
)
from core.utils.download_helpers import parse_downloads

logger = logging.getLogger(__name__)


class RelatedProductSerializer(serializers.ModelSerializer):
    product_type = serializers.SerializerMethodField()
    summary_of_guidance = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "product_code",
            "product_title",
            "product_type",
            "summary_of_guidance",
        )

    def get_product_type(self, obj):
        return obj.update_ref.product_type if obj.update_ref else None

    def get_summary_of_guidance(self, obj):
        return obj.update_ref.summary_of_guidance if obj.update_ref else None


class FileMetadataSerializer(serializers.Serializer):
    URL = serializers.URLField(required=True)
    inline_presigned_s3_url = serializers.URLField(required=False)
    file_size = serializers.CharField(required=True)
    file_type = serializers.CharField(required=True)
    number_of_pages = serializers.CharField(required=False)
    page_size = serializers.CharField(required=False)
    dimensions = serializers.CharField(required=False)
    duration = serializers.CharField(required=False)
    number_of_slides = serializers.CharField(required=False)
    number_of_paragraphs = serializers.CharField(required=False)
    s3_bucket_url = serializers.URLField(required=False)

    # Ensure correct field names in the metadata dictionary
    def validate(self, attrs):
        required_fields = ["URL", "file_size", "file_type", "s3_bucket_url"]
        for field in required_fields:
            if field not in attrs:
                raise serializers.ValidationError({field: f"{field} is required."})
        return attrs


class ProductUpdateSerializer(serializers.ModelSerializer):
    # Required fields
    minimum_stock_level = serializers.IntegerField(required=True)
    maximum_order_quantity = serializers.IntegerField(required=False, allow_null=True)
    run_to_zero = serializers.BooleanField(required=True)
    quantity_available = serializers.IntegerField(required=False)
    available_from_choice = serializers.ChoiceField(
        choices=[
            ("immediately", "Available immediately (allow pre-orders)"),
            ("specific_date", "On a specific date"),
        ],
        required=True,
    )
    available_until_choice = serializers.ChoiceField(
        choices=[
            ("no_end_date", "No End Date"),
            ("specific_date", "On a specific date"),
        ],
        required=True,
    )
    order_end_date = serializers.DateField(required=False, allow_null=True)

    product_type = serializers.ChoiceField(
        required=True,
        choices=PRODUCT_TYPE_CHOICE,
    )

    unit_of_measure = serializers.IntegerField(required=True)

    alternative_type = serializers.ChoiceField(
        choices=ALTERNATIVE_TYPE_CHOICE,
        required=True,
    )
    cost_centre = serializers.ChoiceField(
        choices=COST_CENTRE_CHOICES,
        required=True,
    )
    local_code = serializers.ChoiceField(
        choices=LOCAL_CODES_CHOICES,
        required=True,
    )

    summary_of_guidance = serializers.CharField(required=True)

    # Optional fields
    order_from_date = serializers.DateField(required=False, allow_null=True)
    order_referral_email_address = serializers.EmailField(
        required=True, allow_null=True
    )
    stock_owner_email_address = serializers.EmailField(required=True, allow_null=True)
    order_exceptions = serializers.CharField(required=False, allow_null=True)

    # Add the new product_downloads field
    product_downloads = serializers.SerializerMethodField()

    # Read-only fields
    where_to_use_ref = WhereToUseSerializer(many=True, read_only=True)
    audience_ref = AudienceSerializer(many=True, read_only=True)
    vaccination_ref = VaccinationSerializer(many=True, read_only=True)
    diseases_ref = DiseaseSerializer(many=True, read_only=True)

    # Accept lists of names (required)
    where_to_use_names = serializers.ListField(
        child=serializers.CharField(max_length=255), required=False, allow_empty=True
    )
    audience_names = serializers.ListField(
        child=serializers.CharField(max_length=255), required=False, allow_empty=True
    )
    vaccination_names = serializers.ListField(
        child=serializers.CharField(max_length=255), required=False, allow_empty=True
    )
    disease_names = serializers.ListField(
        child=serializers.CharField(max_length=255), required=False, allow_empty=True
    )

    def __init__(self, *args, **kwargs):
        """
        Override __init__ to dynamically set required fields based on the product's tag.
        """
        super().__init__(*args, **kwargs)

        # Retrieve tag from the context
        tag = self.context.get("tag", None)

        if tag == "download-only":
            optional_fields = [
                "minimum_stock_level",
                "run_to_zero",
                "stock_owner_email_address",
                "order_referral_email_address",
                "cost_centre",
                "local_code",
                "unit_of_measure",
                "order_exceptions",
                "available_from_choice",
                "available_until_choice",
                "order_from_date",
                "order_end_date",
            ]

            # Make these fields NOT required dynamically
            for field in optional_fields:
                if field in self.fields:
                    self.fields[field].required = False
                    self.fields[field].allow_null = True

                self.fields["run_to_zero"].required = False
                self.fields["run_to_zero"].allow_null = True

    class Meta:
        model = ProductUpdate
        fields = [
            "minimum_stock_level",
            "maximum_order_quantity",
            "run_to_zero",
            "quantity_available",
            "available_from_choice",
            "order_from_date",
            "available_until_choice",
            "order_end_date",
            "product_type",
            "alternative_type",
            "cost_centre",
            "local_code",
            "unit_of_measure",
            "summary_of_guidance",
            "order_referral_email_address",
            "stock_owner_email_address",
            "order_exceptions",
            "product_downloads",
            "audience_ref",
            "vaccination_ref",
            "diseases_ref",
            "audience_names",
            "vaccination_names",
            "disease_names",
            "where_to_use_ref",
            "where_to_use_names",
        ]

    def validate(self, data):
        tag = self.context.get("tag", "").strip().lower() if self.context else ""

        if tag == "download-only":
            # Set 'run_to_zero' to False if it's None for 'download-only' tag
            if data.get("run_to_zero") is None:
                data["run_to_zero"] = False
        # Additional validation logic
        if data.get("available_from_choice") == "specific_date" and not data.get(
            "order_from_date"
        ):
            raise serializers.ValidationError(
                "order_from_date is required when available_from_choice is 'specific_date'."
            )
        if data.get("available_until_choice") == "specific_date" and not data.get(
            "order_end_date"
        ):
            raise serializers.ValidationError(
                "order_end_date is required when available_until_choice is 'specific_date'."
            )
        tag = self.context.get("tag", None)

        if tag == "download-only":
            optional_fields = [
                "minimum_stock_level",
                "run_to_zero",
                "stock_owner_email_address",
                "order_referral_email_address",
                "cost_centre",
                "local_code",
                "unit_of_measure",
                "order_exceptions",
                "available_from_choice",
                "available_until_choice",
                "order_from_date",
                "order_end_date",
            ]

            for field in optional_fields:
                self.fields[field].required = False
                data[field] = data.get(
                    field, None
                )  # Allow null values for optional fields
        return data

    def get_product_downloads(self, obj):
        """Return the formatted product_downloads using the shared helper."""
        if obj.product_downloads is None:
            # Return a default structure if product_downloads is None
            return {
                "main_download_url": None,
                "video_url": None,
                "web_download_url": [],
                "print_download_url": [],
                "transcript_url": [],
            }
        return parse_downloads(obj.product_downloads)

    def to_representation(self, instance):
        data = super().to_representation(instance)

        request = self.context.get("request", None)
        if request and hasattr(request, "user"):
            user = request.user
            if user.is_authenticated and hasattr(user, "role_ref") and user.role_ref:
                role_name = (user.role_ref.name or "").strip().lower()
                logger.info(f"User with role '{role_name}' accessed fields.")
                if role_name not in ["admin", "user"]:
                    data.pop("order_referral_email_address", None)
                    data.pop("stock_owner_email_address", None)
            else:
                logger.warning("Non-authenticated or role-less user accessed fields.")
                data.pop("order_referral_email_address", None)
                data.pop("stock_owner_email_address", None)
        else:
            logger.warning("Request or user not found in serializer context.")
            data.pop("order_referral_email_address", None)
            data.pop("stock_owner_email_address", None)

        return data


class ProductSerializer(serializers.ModelSerializer):
    status = serializers.CharField(max_length=50, default="draft")
    suppress_event = serializers.BooleanField(default=False, required=False)
    product_key = serializers.CharField(max_length=50)
    program_id = serializers.SlugRelatedField(
        slug_field="program_id", queryset=Program.objects.all()
    )
    order_limits = OrderLimitPageSerializer(many=True, read_only=True)

    language_id = serializers.SlugRelatedField(
        slug_field="language_id", queryset=LanguagePage.objects.all()
    )

    language_name = serializers.CharField(read_only=True)
    existing_languages = serializers.SerializerMethodField()

    tag = serializers.ChoiceField(
        choices=[
            ("download-only", "Download Only"),
            ("download-or-order", "Download or Order"),
            ("order-only", "Order Only"),
        ],
        required=True,
    )
    suppress_event = serializers.BooleanField(default=False, required=False)

    update_ref = ProductUpdateSerializer(read_only=True)
    product_code_no_dashes = serializers.CharField(read_only=True)
    user_order_limit = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "product_id",
            "product_title",
            "language_id",
            "file_url",
            "product_key",
            "program_id",
            "existing_languages",
            "status",
            "tag",
            "publish_date",
            "is_latest",
            "language_name",
            "user_ref",
            "program_name",
            "iso_language_code",
            "product_code",
            "product_code_no_dashes",
            "version_number",
            "suppress_event",
            "update_ref",
            "order_limits",
            "user_order_limit",
            "created_at",
            "updated_at",
        )

    def validate(self, data):
        self.context["tag"] = data.get("tag", None)
        return data

    def get_existing_languages(self, obj):
        return obj.existing_languages

    def get_user_order_limit(self, obj):
        """
        Return the order_limit for this product for the current user's organisation.
        If the user is not authenticated, has no organisation, or no matching
        OrderLimitPage exists, return None.
        """
        request = self.context.get("request")
        if not request:
            return None

        user = getattr(request, "user", None)
        # Your custom User has its own is_authenticated, but this guards the DRF/AnonUser too
        if not user or not getattr(user, "is_authenticated", False):
            return 5  # Default order limit for unauthenticated users

        org = getattr(user, "organization_ref", None)
        if not org:
            return 5  # Default order limit for users without an organization

        # Use the reverse relation: Product -> OrderLimitPage (order_limits)
        # If order_limits is prefetched, this stays in memory; otherwise it's a small query.
        try:
            limit_obj = obj.order_limits.filter(organization_ref=org).first()
        except Exception:
            # Defensive: if for some reason order_limits is not a manager
            return None

        if not limit_obj:
            return None

        return limit_obj.order_limit

    def create(self, validated_data):
        # Check if the 'product_id' is provided in the request
        product_id = validated_data.get("product_id", None)
        if not product_id:
            validated_data[
                "product_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)


class AdminProductSerializer(ProductSerializer):
    last_updated_by = serializers.SerializerMethodField()
    last_updated_by_initials = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    created_by_initials = serializers.SerializerMethodField()

    class Meta(ProductSerializer.Meta):
        fields = ProductSerializer.Meta.fields + (
            "last_updated_by",
            "last_updated_by_initials",
            "created_by",
            "created_by_initials",
        )

    # ---------------- last updated ----------------

    def get_last_updated_by(self, obj):
        user = getattr(obj, "user_ref", None)
        return f"{user.first_name} {user.last_name}".strip() if user else None

    def get_last_updated_by_initials(self, obj):
        user = getattr(obj, "user_ref", None)
        if not user:
            return None
        return f"{user.first_name[:1]}{user.last_name[:1]}".upper()

    # ---------------- created by (uses annotations) ----------------

    def get_created_by(self, obj):
        name = getattr(obj, "creator_display_name", None)
        return name or None

    def get_created_by_initials(self, obj):
        name = getattr(obj, "creator_display_name", None)
        if not name:
            return None
        parts = [p for p in name.split() if p]
        return "".join(p[0].upper() for p in parts[:2])


class ProductUpdateSearchSerializer(serializers.ModelSerializer):
    """
    A lightweight serializer for nested update data, which only returns
    product_downloads and summary_of_guidance.
    """

    product_downloads = serializers.SerializerMethodField()

    class Meta:
        model = ProductUpdate
        fields = (
            "summary_of_guidance",
            "product_downloads",
            "available_from_choice",
            "order_from_date",
            "available_until_choice",
            "order_end_date",
            "minimum_stock_level",
            "run_to_zero",
            "unit_of_measure",
        )

    def get_product_downloads(self, obj):
        """Return the formatted product_downloads using the shared helper."""
        return parse_downloads(obj.product_downloads)


class ProductSearchSerializer(serializers.ModelSerializer):
    """
    Serializer used only in search endpoints to return a restricted set
    of fields.
    """

    update_ref = ProductUpdateSearchSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    updated_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Product
        fields = (
            "product_title",
            "product_code",
            "update_ref",
            "tag",
            "status",
            "program_id",
            "product_key",
            "language_id",
            "language_name",
            "product_code_no_dashes",
            "created_at",
            "updated_at",
            "publish_date",
            "version_number",
            "suppress_event",
        )
