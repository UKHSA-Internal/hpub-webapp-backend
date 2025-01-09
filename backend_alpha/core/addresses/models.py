import uuid

from core.users.models import User
from django.db import models
from django.utils.timezone import now
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


class Address(Page):
    address_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    address_line1 = models.CharField(max_length=255, blank=True, null=True)
    address_line2 = models.CharField(max_length=255, blank=True, null=True)
    address_line3 = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    county = models.CharField(max_length=200, blank=True, null=True)
    postcode = models.CharField(max_length=20, blank=True, null=True)
    country = models.CharField(max_length=100, blank=True, null=True)
    is_default = models.BooleanField(default=False, blank=True, null=True)
    verified = models.BooleanField(default=False, blank=True, null=True)
    user_ref = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="addresses"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now_add=True)

    content_panels = Page.content_panels + [
        FieldPanel("address_line1"),
        FieldPanel("address_line2"),
        FieldPanel("address_line3"),
        FieldPanel("city"),
        FieldPanel("county"),
        FieldPanel("postcode"),
        FieldPanel("country"),
        FieldPanel("is_default"),
        FieldPanel("verified"),
    ]

    def __str__(self):
        return f"{self.address_line1}, {self.city}, {self.country}"

    def save(self, *args, **kwargs):
        if not self.pk:  # if the object is new
            self.created_at = now()
        self.modified_at = now()
        super().save(*args, **kwargs)
