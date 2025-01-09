from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


class Program(Page):
    programme_name = models.CharField(max_length=100, unique=True)
    external_key = models.CharField(max_length=100, null=True, blank=True)
    is_featured = models.BooleanField(default=False)
    is_temporary = models.BooleanField(default=False)
    program_id = models.CharField(
        max_length=22, primary_key=True, unique=True, editable=False
    )

    program_term = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        choices=[
            ("short_term", "Short Term"),
            ("long_term", "Long Term"),
        ],
    )

    content_panels = Page.content_panels + [
        FieldPanel("programme_name"),
        FieldPanel("is_featured"),
        FieldPanel("is_temporary"),
        FieldPanel("program_term"),
        FieldPanel("external_key"),
    ]

    def __str__(self):
        return self.programme_name
