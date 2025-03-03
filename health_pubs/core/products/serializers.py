import uuid
import json
from core.audiences.serializers import AudienceSerializer
from core.diseases.serializers import DiseaseSerializer
from core.languages.models import LanguagePage
from core.order_limits.serializers import OrderLimitPageSerializer
from core.programs.models import Program
from core.users.serializers import UserSerializer
from core.vaccinations.serializers import VaccinationSerializer
from core.where_to_use.serializers import WhereToUseSerializer
from rest_framework import serializers

from .models import Product, ProductUpdate


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
    maximum_order_quantity = serializers.IntegerField(required=True)
    run_to_zero = serializers.BooleanField(required=True)
    quantity_available = serializers.IntegerField(required=False)
    available_from_choice = serializers.ChoiceField(
        choices=[
            ("immediately", "Available immediately (allow pre-orders)"),
            ("specific_date", "On a specific date"),
        ],
        required=True,
    )
    order_end_date = serializers.DateField(required=True)

    product_type = serializers.ChoiceField(
        required=True,
        choices=[
            ("Audio", "Audio"),  # main download, transcript download, web_download
            ("Transcript", "Transcript"),
            ("Bulletins", "Bulletins"),  # main download, print download, web_download
            ("Consent Form", "Consent Form"),
            ("Images", "Images"),
            ("Leaflets", "Leaflets"),
            ("Postcards", "Postcards"),
            ("Posters", "Posters"),
            ("Pull-up Banners", "Pull-up Banners"),
            ("Stickers", "Stickers"),
            ("Record Cards", "Record Cards"),
            ("Record Card", "Record Card"),  # singular version
            ("Z-Card", "Z-Card"),
            ("Fridge Magnet", "Fridge Magnet"),
            ("Flyer", "Flyer"),
            ("Invitation Letter", "Invitation Letter"),
            ("Alternative", "Alternative"),
            ("Memoire", "Memoire"),
            ("Guidance", "Guidance"),
            ("Video", "Video"),  # main download, web_download
            ("GIF", "GIF"),
            ("Slides", "Slides"),
            ("Factsheets", "Factsheets"),
            ("Briefing Sheet", "Briefing Sheet"),
            ("Flip Chart", "Flip Chart"),
            ("Immunisation Schedule", "Immunisation Schedule"),
            ("Booklet", "Booklet"),
            ("Envelope Label", "Envelope Label"),
            ("Pack Sleeve", "Pack Sleeve"),  # Added
            ("Slide", "Slide"),  # Singular Slide explicitly added
            ("Audio Transcript", "Audio Transcript"),  # Derived from provided context
        ],
    )

    unit_of_measure = serializers.IntegerField(required=True)

    alternative_type = serializers.ChoiceField(
        choices=[
            ("Video and Audio", "Video and Audio"),
            ("Braille", "Braille"),
            ("Easy read", "Easy read"),
            ("British Sign Language (BSL)", "British Sign Language (BSL)"),
            ("Large print", "Large print"),
        ],
        required=True,
    )
    cost_centre = serializers.ChoiceField(
        choices=[
            ("10200", "10200"),
            ("22820", "22820"),
            ("24839", "24839"),
            ("25050", "25050"),
            ("25430", "25430"),
            ("25460", "25460"),
            ("29415", "29415"),
            ("KEA4", "KEA4"),
            ("UFA8", "UFA8"),
            ("UFB3", "UFB3"),
            ("UGB6", "UGB6"),
            ("UGB7", "UGB7"),
            ("UGB9", "UGB9"),
            ("UIA1", "UIA1"),
            ("UIA4", "UIA4"),
            ("UMA2", "UMA2"),
            ("UMA5", "UMA5"),
            ("UMA8", "UMA8"),
            ("UMB8", "UMB8"),
            ("VEA6", "VEA6"),
            ("VEA7", "VEA7"),
        ],
        required=True,
    )
    local_code = serializers.ChoiceField(
        choices=[
            ("0001", "0001"),
            ("1000", "1000"),
            ("10000", "10000"),
            ("1100", "1100"),
            ("11000", "11000"),
            ("14000", "14000"),
            ("2000", "2000"),
            ("3000", "3000"),
            ("4000", "4000"),
            ("51005", "51005"),
            ("6000", "6000"),
            ("7000", "7000"),
            ("9000", "9000"),
            ("9500", "9500"),
            ("BE0026", "BE0026"),
            ("CAB-1", "CAB-1"),
            ("FID038", "FID038"),
        ],
        required=True,
    )

    summary_of_guidance = serializers.CharField(required=True)

    # Optional fields
    order_from_date = serializers.DateField(required=False, allow_null=True)
    order_referral_email_address = serializers.EmailField(
        required=False, allow_null=True
    )
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

    class Meta:
        model = ProductUpdate
        fields = [
            "minimum_stock_level",
            "maximum_order_quantity",
            "run_to_zero",
            "quantity_available",
            "available_from_choice",
            "order_from_date",
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
        # Add any additional validation logic here
        if data.get("available_from_choice") == "specific_date" and not data.get(
            "order_from_date"
        ):
            raise serializers.ValidationError(
                "order_from_date is required when available_from_choice is 'specific_date'."
            )
        return data

    def get_product_downloads(self, obj):
        """Ensure product_downloads is a dictionary before accessing it."""
        try:
            # Deserialize only if it's a string
            downloads = (
                json.loads(obj.product_downloads)
                if isinstance(obj.product_downloads, str)
                else obj.product_downloads
            )
        except json.JSONDecodeError:
            downloads = {}

        return {
            "main_download_url": downloads.get("main_download_url"),
            "video_url": downloads.get("video_url"),
            "web_download_url": [
                FileMetadataSerializer(m).data
                for m in downloads.get("web_download_url", [])
            ],
            "print_download_url": [
                FileMetadataSerializer(m).data
                for m in downloads.get("print_download_url", [])
            ],
            "transcript_url": [
                FileMetadataSerializer(m).data
                for m in downloads.get("transcript_url", [])
            ],
        }


class ProductSerializer(serializers.ModelSerializer):
    status = serializers.CharField(max_length=50, default="draft")
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

    update_ref = ProductUpdateSerializer(read_only=True)
    product_code_no_dashes = serializers.CharField(read_only=True)

    user_info = serializers.SerializerMethodField()

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
            "user_info",
            "program_name",
            "iso_language_code",
            "product_code",
            "product_code_no_dashes",
            "version_number",
            "update_ref",
            "order_limits",
            "created_at",
            "updated_at",
        )

    def validate(self, data):
        return data

    def get_existing_languages(self, obj):
        return obj.existing_languages

    def create(self, validated_data):
        # Check if the 'product_id' is provided in the request
        product_id = validated_data.get("product_id", None)
        if not product_id:
            validated_data[
                "product_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)

    def get_user_info(self, obj):
        if obj.user_ref:
            # Serialize and return user info
            return UserSerializer(obj.user_ref).data
        return None
