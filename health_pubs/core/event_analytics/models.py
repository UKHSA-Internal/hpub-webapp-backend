from django.db import models
from wagtail.models import Page
from wagtail.admin.panels import FieldPanel
from core.users.models import User
import uuid


class EventAnalytics(Page):
    event_analytics_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    event_type = models.CharField(
        max_length=50,
        choices=(
            ("basket_add", "Basket Add"),
            ("basket_remove", "Basket Remove"),
            ("basket_abandoned", "Basket Abandoned"),
            ("order", "Order"),
            ("reorder", "Reorder"),
            ("download", "Download"),
        ),
    )
    user_ref = models.ForeignKey(
        User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="event_analytics",
    )
    session_id = models.CharField(max_length=100)
    timestamp = models.DateTimeField(auto_now_add=True)
    metadata = models.JSONField(default=dict, blank=True)

    content_panels = Page.content_panels + [
        FieldPanel("event_type"),
        FieldPanel("session_id"),
        FieldPanel("metadata"),
        FieldPanel("user_ref"),
    ]

    def __str__(self):
        return f"{self.event_type} at {self.timestamp}"
