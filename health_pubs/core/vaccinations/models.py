import uuid

from core.programs.models import Program
from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


class Vaccination(Page):
    vaccination_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, null=True)
    key = models.CharField(max_length=255, blank=True, null=True)
    programs = models.ManyToManyField(
        Program,
        blank=True,
        related_name="vaccinations",
    )
    # Will be using this code for later client development for MVP
    # diseases = models.ManyToManyField(
    #     'core.diseases.Disease',
    #     blank=True,
    #     related_name="vaccinations",
    # )

    content_panels = Page.content_panels + [
        FieldPanel("name"),
        FieldPanel("description"),
        FieldPanel("key"),
        FieldPanel("programs"),
        # FieldPanel("diseases"),
    ]

    def __str__(self):
        return self.name
