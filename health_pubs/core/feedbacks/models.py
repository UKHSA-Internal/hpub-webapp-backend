import uuid

from core.users.models import User
from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


# Feedback Model
class Feedback(Page):
    feedback_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    user_ref = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    message = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    content_panels = Page.content_panels + [
        FieldPanel("user_ref"),
        FieldPanel("message"),
    ]

    def __str__(self):
        return f"Feedback from {self.user} - {self.submitted_at}"
