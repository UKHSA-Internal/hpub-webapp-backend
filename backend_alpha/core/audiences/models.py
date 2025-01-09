import uuid

from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


class Audience(Page):
    audience_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
        max_length=225,
    )
    name = models.CharField(max_length=255, unique=True)
    description = models.TextField(blank=True, null=True)
    key = models.CharField(max_length=255, blank=True, null=True, unique=True)

    content_panels = Page.content_panels + [
        FieldPanel("name"),
        FieldPanel("description"),
        FieldPanel("key"),
    ]

    def __str__(self):
        return self.name
