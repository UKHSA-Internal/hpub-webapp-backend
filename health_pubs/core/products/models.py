import os, re
import sys
import uuid
from django.utils import timezone
from urllib.parse import quote
from itertools import takewhile

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
    last_updated_by_name = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Full name (first + last) of the user who last updated this product.",
    )
    last_updated_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Timestamp of the last product update (via PATCH or admin).",
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

    # ---------------------------
    # Save hook
    # ---------------------------
    def save(self, *args, **kwargs):
        now = timezone.now()

        if self._state.adding:
            if self.created_at is None:
                self.created_at = now
            if self.updated_at is None:
                self.updated_at = now
        else:
            self.updated_at = now
            # Keep last_updated_at in sync unless overridden
            if not self.last_updated_at:
                self.last_updated_at = now

        if self.product_code:
            self.product_code_no_dashes = (
                str(self.product_code).replace("-", "").replace(" ", "")
            )

        super().save(*args, **kwargs)

    # ---------------------------
    # Helpers
    # ---------------------------
    def is_due_to_publish(self):
        return (
            self.status == "draft"
            and self.publish_date is not None
            and self.publish_date <= timezone.now()
        )

    def __str__(self):
        return self.product_title

    # ======== Series parsing (DoS-safe, no catastrophic backtracking) ========

    @staticmethod
    def _normalize_code(code: str) -> str:
        if not isinstance(code, str):
            return ""
        # remove spaces/dashes, upper-case
        return re.sub(r"[\s-]+", "", code.upper())

    @staticmethod
    def _sanitize_lang_hint(lang: str | None) -> str:
        if not lang:
            return ""
        # letters only, up to 4
        return re.sub(r"[^A-Z]", "", str(lang).upper())[:4]

    @staticmethod
    def _split_lang_version(
        norm: str, lang_hint: str | None = None, max_total_len: int = 512
    ):
        """
        Return (prefix, lang, version) where code = prefix + lang + version(3 digits).

        Strategy:
        - Require last 3 chars to be digits (version).
        - If a language hint is provided (recommended), require code to end with that exact
          letters-only LANG (2..4) + version.
        - Otherwise, fall back to 'exactly 2 trailing letters' as LANG to avoid consuming
          product-key letters into LANG by accident.
        """
        if not norm or len(norm) > max_total_len or len(norm) < 5:
            return None

        ver = norm[-3:]
        if not ver.isdigit():
            return None

        hint = Product._sanitize_lang_hint(lang_hint)
        if 2 <= len(hint) <= 4 and norm.endswith(hint + ver):
            return (norm[: -(len(hint) + 3)], hint, ver)

        # Fallback: treat LANG as exactly 2 trailing letters before version
        if len(norm) >= 5 and norm[-4:-2].isalpha():
            lang = norm[-4:-2]
            return (norm[:-5], lang, ver)

        return None

    @staticmethod
    def _series_root_from_prefix(prefix: str, min_digit_run: int = 1) -> str:
        """
        From the prefix (before LANG), take the RIGHTMOST block:
           digits_run + letters_run
        where letters_run are contiguous A–Z right before LANG, and digits_run is the
        contiguous digits immediately before those letters (or end if no letters).
        Return digits_run + letters_run.

        Example extractions:
          '240377D'   -> '240377D'
          '240377FB'  -> '240377FB'
          '2023'      -> '2023'
          '12AB34E'   -> '34E'
        """
        if not prefix:
            return ""
        i = len(prefix) - 1

        # 1) Gather letters immediately before LANG (if any)
        while i >= 0 and "A" <= prefix[i] <= "Z":
            i -= 1
        letters = prefix[i + 1 :]  # may be ""

        # 2) Gather the digit run immediately before those letters (or end)
        j = i
        while j >= 0 and prefix[j].isdigit():
            j -= 1
        digits = prefix[j + 1 : i + 1]

        if len(digits) < min_digit_run:
            return ""
        return digits + letters

    @staticmethod
    def _is_standard_series_code(code: str) -> bool:
        """
        Standard if we can split into <prefix><LANG><3 digits> and extract a root
        (digits + immediate letters) from the prefix.
        """
        norm = Product._normalize_code(code)
        parts = Product._split_lang_version(norm, None)
        if not parts:
            return False
        prefix, _lang, _ver = parts
        return Product._series_root_from_prefix(prefix) != ""

    @staticmethod
    def _standard_root(code: str, lang_hint: str | None = None) -> str:
        """
        The 'series root' = digits just before LANG + any letters immediately before LANG.
        If lang_hint is provided (recommended), we split using that exact LANG.
        """
        norm = Product._normalize_code(code)
        parts = Product._split_lang_version(norm, lang_hint)
        if not parts:
            return ""
        prefix, _lang, _ver = parts
        return Product._series_root_from_prefix(prefix)

    @staticmethod
    def _series_info(code: str, lang_hint: str | None = None) -> tuple[str, str]:
        root = Product._standard_root(code, lang_hint)
        if root:
            return "standard", root
        return "irregular", Product._irregular_root(code)

    @staticmethod
    def _irregular_root(code: str) -> str:
        # Keep as-is; these are anchored/simple and not prone to catastrophic backtracking.
        norm = Product._normalize_code(code)
        m = re.match(r"^([A-Z]{2,}\d+)[A-Z]{2,3}$", norm)
        if m:
            return m.group(1)
        m = re.match(r"^([A-Z]{2,})\d+$", norm)
        if m:
            return m.group(1)
        m = re.match(r"^([A-Z]{2,})", norm)
        return m.group(1) if m else ""

    @staticmethod
    def _get_common_prefix(a: str, b: str, min_length: int = 3) -> str:
        a, b = a or "", b or ""
        matched = takewhile(lambda pair: pair[0] == pair[1], zip(a, b))
        prefix = "".join(ch for ch, _ in matched)
        return prefix if len(prefix) >= min_length else ""

    def _format_language(
        self, data: dict, domain: str, wanted_root: str, wanted_kind: str
    ) -> dict | None:
        code = data.get("product_code")
        if not code:
            return None

        # Use the row's lang as a hint for robust splitting
        _, c_root = self._series_info(code, data.get("iso_language_code"))
        if c_root != wanted_root:
            return None

        title = (data.get("product_title") or "").strip()
        if not title:
            return None

        lang_name = data.get("language_name", "") or ""
        version = int(data.get("version_number") or 0)
        alt = data.get("update_ref__alternative_type")
        ptype = data.get("update_ref__product_type")

        if wanted_kind == "irregular" and version == 1 and alt:
            suffix = ptype if (alt == "not-accessible" and ptype) else alt
            if suffix:
                lang_name = f"{lang_name}: {suffix}"

        title_enc = quote(title, safe="")
        code_enc = quote(code, safe="")

        return {
            "language_name": lang_name,
            "product_url": f"{domain}/{title_enc}/{code_enc}",
            "iso_language_code": data.get("iso_language_code"),
        }

    @property
    def existing_languages(self) -> list[dict]:
        try:
            domain = Config().get_hpub_base_api_url().rstrip("/")
        except Exception:
            domain = ""

        code = getattr(self, "product_code", None)
        if not isinstance(code, str):
            return []

        # Use self.iso_language_code as a hint for correct grouping
        kind, root = self._series_info(code, self.iso_language_code)
        if not root:
            return []

        qs = Product.objects.filter(
            program_id=self.program_id, is_latest=True, status="live"
        ).exclude(pk=self.pk)

        if self.product_key:
            keyed = qs.filter(product_key=self.product_key)
            if keyed.exists():
                qs = keyed

        vals = qs.values(
            "language_name",
            "product_title",
            "product_code",
            "iso_language_code",
            "version_number",
            "update_ref__alternative_type",
            "update_ref__product_type",
        )

        langs = [
            formatted
            for row in vals
            for formatted in [self._format_language(row, domain, root, kind)]
            if formatted is not None
        ]
        return langs


#
