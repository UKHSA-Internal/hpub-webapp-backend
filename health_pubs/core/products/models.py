import os
import sys
import uuid
from django.utils import timezone

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
import logging
from .choices import (
    COST_CENTRE_CHOICES,
    LOCAL_CODES_CHOICES,
    PRODUCT_TYPE_CHOICE,
    ALTERNATIVE_TYPE_CHOICE,
)

logger = logging.getLogger(__name__)


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
    )

    order_from_date = models.DateField(null=True, blank=True)  # optional

    # Available Until Choices
    AVAILABLE_UNTIL_CHOICES = [
        ("no_end_date", "No End Date"),
        ("specific_date", "On a specific date"),
    ]

    available_until_choice = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=AVAILABLE_UNTIL_CHOICES,
    )

    order_end_date = models.DateField(blank=True, null=True)

    # Publication and Alternative Types
    product_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=PRODUCT_TYPE_CHOICE,
    )

    alternative_type = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=ALTERNATIVE_TYPE_CHOICE,
    )

    # Cost Centre and Local Code
    cost_centre = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=COST_CENTRE_CHOICES,
    )

    local_code = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=LOCAL_CODES_CHOICES,
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
        FieldPanel("available_until_choice"),
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
    suppress_event = models.BooleanField(
        default=False,
        help_text="When true, suppress all EventBridge events on status changes.",
    )

    created_at = models.DateTimeField(
        default=timezone.now,
        blank=True,
        help_text="If not provided, set to now on first save.",
    )
    updated_at = models.DateTimeField(
        default=timezone.now,
        blank=True,
        help_text="If not provided, set to now on every save.",
    )

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
        FieldPanel("suppress_event"),
    ]

    def save(self, *args, **kwargs):
        now = timezone.now()

        if self._state.adding:
            # new instance…
            if self.created_at is None:
                self.created_at = now
            # only set updated_at on create if nobody passed one
            if self.updated_at is None:
                self.updated_at = now
        else:
            # existing instance: always bump updated_at
            self.updated_at = now

        # keep your product_code_no_dashes logic
        if self.product_code:
            self.product_code_no_dashes = self.product_code.replace("-", "").replace(
                " ", ""
            )

        super().save(*args, **kwargs)

    def is_due_to_publish(self):
        return (
            self.status == "draft"
            and self.publish_date is not None
            and self.publish_date <= timezone.now()
        )

    def __str__(self):
        return self.product_title

    def _get_core_code(self, code, required_length=3):
        """
        Extracts the core part of a product code.

        Args:
            code (str): The product code.
            required_length (int): Minimum length needed to extract the core.

        Returns:
            str: The core of the product code, or an empty string if not valid.
        """
        if not isinstance(code, str):
            return ""
        if len(code) < required_length:
            return ""
        return code[:required_length]

    def _get_common_prefix(self, other: str, min_length: int = 3) -> str:
        """
        Longest common prefix between self.product_code and other,
        provided it's at least `min_length` chars.
        """
        a = self.product_code or ""
        b = other or ""
        prefix = []
        for ch1, ch2 in zip(a, b):
            if ch1 == ch2:
                prefix.append(ch1)
            else:
                break
        prefix = "".join(prefix)
        return prefix if len(prefix) >= min_length else ""

    @property
    def existing_languages(self):
        """
        Find all other `live` & `is_latest` products in the same program,
        prefer those sharing `product_key` if any exist, then filter by
        having a common prefix >= 3 chars.
        """
        # 1) base URL
        try:
            domain = Config().get_hpub_base_api_url().rstrip("/")
        except Exception as e:
            logger.error("Config error: %s", e)
            return []

        # 2) our code
        my_code = getattr(self, "product_code", None)
        if not isinstance(my_code, str):
            logger.error("Missing product_code on %r", self)
            return []

        # 3) fetch siblings
        base_qs = Product.objects.filter(
            program_id=self.program_id,
            is_latest=True,
            status="live",
        ).exclude(pk=self.pk)

        # if any share this product_key, narrow to them
        if self.product_key:
            keyed = base_qs.filter(product_key=self.product_key)
            qs = keyed if keyed.exists() else base_qs
        else:
            qs = base_qs

        # 4) build list by prefix match
        langs = []
        for p in qs.values("language_name", "product_title", "product_code"):
            cand = p["product_code"]
            prefix = self._get_common_prefix(cand)
            if not prefix:
                continue

            title = p["product_title"] or ""
            if not title:
                logger.warning("No title for %r", cand)
                continue

            slug = slugify(title)
            url = f"{domain}/{slug}/{cand}"
            langs.append(
                {
                    "language_name": p["language_name"],
                    "product_url": url,
                }
            )
        logger.debug("Existing languages: %s", langs)

        return langs


#
