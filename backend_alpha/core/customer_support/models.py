import uuid

from core.users.models import User
from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


class CustomerSupport(Page):
    customer_support_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    user_ref = models.ForeignKey(
        User,
        null=True,
        on_delete=models.SET_NULL,
        blank=True,
    )
    message = models.TextField(max_length=500, blank=True, null=True)
    summary = models.CharField(max_length=100, blank=True, null=True)
    contact_name = models.TextField(blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    content_panels = Page.content_panels + [
        FieldPanel("user_ref"),
        FieldPanel("message"),
        FieldPanel("summary"),
        FieldPanel("contact_name"),
        FieldPanel("contact_email"),
    ]

    def __str__(self):
        return self.message
