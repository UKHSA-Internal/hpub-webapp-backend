import uuid

from core.organizations.models import Organization
from django.db import models
from wagtail.models import Page


class Establishment(Page):
    establishment_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    organization_ref = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="establishments",
    )
    name = models.CharField(max_length=100)
    external_key = models.CharField(max_length=100, blank=True, null=True)
    full_external_key = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name
