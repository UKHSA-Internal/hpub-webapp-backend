import uuid

from core.programs.models import Program
from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


class Disease(Page):
    disease_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    name = models.CharField(max_length=255, unique=True)
    key = models.TextField(blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    programs = models.ManyToManyField(
        Program,
        related_name="diseases",
        blank=True,
    )

    content_panels = Page.content_panels + [
        FieldPanel("name"),
        FieldPanel("key"),
        FieldPanel("description"),
        FieldPanel("programs"),
    ]

    def __str__(self):
        return self.name
