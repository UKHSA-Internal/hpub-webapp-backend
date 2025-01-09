import os
import sys
import uuid

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
from configs.get_secret_config import Config
from core.audiences.models import Audience
from core.diseases.models import Disease
from core.languages.models import LanguagePage
from core.programs.models import Program
from core.users.models import User
from core.vaccinations.models import Vaccination
from core.where_to_use.models import WhereToUse
from django.db import models
from django.utils.text import slugify
from wagtail.admin.panels import FieldPanel
from wagtail.fields import RichTextField
from wagtail.models import Page


class ProductUpdate(Page):
    minimum_stock_level = models.IntegerField(blank=True, null=True)

    maximum_order_quantity = models.IntegerField(blank=True, null=True)

    quantity_available = models.IntegerField(blank=True, null=False, default=0)

    run_to_zero = models.BooleanField(blank=True, null=False, default=False)

    # Available From Choices
    AVAILABLE_FROM_CHOICES = [
        ("immediately", "Available immediately (allow pre-orders)"),
        ("specific_date", "On a specific date"),
    ]

    available_from_choice = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=AVAILABLE_FROM_CHOICES,
        default="immediately",
    )

    order_from_date = models.DateField(null=True, blank=True)  # optional

    order_end_date = models.DateField(blank=True, null=True)

    # Publication and Alternative Types
    product_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
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

    alternative_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=[
            ("Video and Audio", "Video and Audio"),
            ("Simple Text", "Simple Text"),
            ("Braille", "Braille"),
            ("Easy read", "Easy read"),
            ("British Sign Language (BSL)", "British Sign Language (BSL)"),
            ("Large print", "Large print"),
        ],
    )

    # Cost Centre and Local Code
    cost_centre = models.CharField(
        max_length=50,
        null=True,
        blank=True,
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
        default="10200",
    )

    local_code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
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
        default="0001",
    )

    unit_of_measure = models.IntegerField(null=True, blank=True)

    # Summary and QR Code URL
    summary_of_guidance = RichTextField(blank=True, null=True)

    product_downloads = models.JSONField(default=dict, blank=True, null=True)

    main_download_url = models.JSONField(default=list, blank=True)
    video_url = models.URLField(blank=True, null=True)
    print_download_url = models.JSONField(default=list, blank=True)
    web_download_url = models.JSONField(default=list, blank=True)
    transcript_url = models.JSONField(default=list, blank=True)

    # Foreign Key Relationships
    where_to_use_ref = models.ManyToManyField(WhereToUse, blank=True)
    audience_ref = models.ManyToManyField(Audience, blank=True)
    vaccination_ref = models.ManyToManyField(Vaccination, blank=True)
    diseases_ref = models.ManyToManyField(Disease, blank=True)

    # Email Fields
    order_referral_email_address = models.EmailField(blank=True, null=True)  # optional
    stock_owner_email_address = models.EmailField(blank=True, null=True)

    # order exceptions
    order_exceptions = RichTextField(blank=True, null=True)

    # Wagtail Admin Panels
    content_panels = [
        FieldPanel("minimum_stock_level"),
        FieldPanel("maximum_order_quantity"),
        FieldPanel("run_to_zero"),
        FieldPanel("quantity_available"),
        FieldPanel("available_from_choice"),
        FieldPanel("order_from_date"),
        FieldPanel("order_end_date"),
        FieldPanel("product_type"),
        FieldPanel("alternative_type"),
        FieldPanel("cost_centre"),
        FieldPanel("local_code"),
        FieldPanel("unit_of_measure"),
        FieldPanel("summary_of_guidance"),
        FieldPanel("order_exceptions"),
        FieldPanel("main_download_url"),
        FieldPanel("print_download_url"),
        FieldPanel("web_download_url"),
        FieldPanel("transcript_url"),
        FieldPanel("video_url"),
        FieldPanel("audience_ref"),
        FieldPanel("vaccination_ref"),
        FieldPanel("diseases_ref"),
        FieldPanel("where_to_use_ref"),
        FieldPanel("order_referral_email_address"),
        FieldPanel("stock_owner_email_address"),
        FieldPanel("product_downloads"),
    ]

    def __str__(self):
        return f"Update for Product {self.id}"


class Product(Page):
    product_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    user_ref = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="products"
    )
    language_id = models.ForeignKey(
        LanguagePage, null=True, on_delete=models.SET_NULL, related_name="products"
    )

    program_id = models.ForeignKey(
        Program,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="products",
    )
    product_key = models.CharField(max_length=50)
    publish_date = models.DateField(null=True, blank=True)
    program_name = models.CharField(max_length=255)
    iso_language_code = models.CharField(max_length=10)
    product_code = models.CharField(max_length=255, unique=True)
    product_code_no_dashes = models.CharField(max_length=255, editable=False, null=True)
    version_number = models.IntegerField()
    product_title = models.CharField(max_length=255)
    is_latest = models.BooleanField(default=True)
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("live", "Live"),
        ("archived", "Archived"),
        ("withdrawn", "Withdrawn"),
    ]

    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default="draft")

    tag = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=[
            ("download-only", "Download Only"),
            ("download-or-order", "Download or Order"),
            ("order-only", "Order Only"),
        ],
    )

    language_name = models.CharField(max_length=30)

    file_url = models.URLField(max_length=255, null=True, blank=True)

    # Reference to ProductUpdate (optional)
    update_ref = models.OneToOneField(
        ProductUpdate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="product",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # Panels for Wagtail Admin
    content_panels = Page.content_panels + [
        FieldPanel("user_ref"),
        FieldPanel("program_id"),
        FieldPanel("product_key"),
        FieldPanel("publish_date"),
        FieldPanel("program_name"),
        FieldPanel("iso_language_code"),
        FieldPanel("product_code"),
        FieldPanel("is_latest"),
        FieldPanel("version_number"),
        FieldPanel("product_title"),
        FieldPanel("language_id"),
        FieldPanel("language_name"),
        FieldPanel("status"),
        FieldPanel("file_url"),
        FieldPanel("update_ref"),
        FieldPanel("tag"),
    ]

    def save(self, *args, **kwargs):
        # Automatically populate `product_code_no_dashes` by removing dashes and spaces
        if self.product_code:
            self.product_code_no_dashes = self.product_code.replace("-", "").replace(
                " ", ""
            )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.product_title

    @property
    def existing_languages(self):
        config = Config()
        related_products = Product.objects.filter(
            program_id=self.program_id, product_key=self.product_key, is_latest=True
        ).exclude(language_id=self.language_id, product_title=self.product_title)

        domain_name = config.get_hpub_base_api_url()
        existing_languages = []
        for product in related_products:
            product_url = (
                f"{domain_name}/{slugify(product.product_title)}/{product.product_code}"
            )
            existing_languages.append(
                {"language_name": product.language_name, "product_url": product_url}
            )

        return existing_languages
