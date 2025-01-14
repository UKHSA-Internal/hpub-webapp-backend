import uuid

from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


class LanguagePage(Page):
    language_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    language_names = models.CharField(
        max_length=100, unique=True, help_text="Full name of the language"
    )
    iso_language_code = models.CharField(
        max_length=25, help_text="The bcp47 code of the language name"
    )

    content_panels = Page.content_panels + [
        FieldPanel("language_names"),
        FieldPanel("iso_language_code"),
    ]

    def __str__(self):
        return str(self.language_id)
