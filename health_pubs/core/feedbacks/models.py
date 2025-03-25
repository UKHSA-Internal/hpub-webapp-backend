import uuid

from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page
from core.users.models import User


class Feedback(Page):
    feedback_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    user_ref = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="feedbacks"
    )
    SATISFACTION_CHOICES = [
        ("very_satisfied", "Very satisfied"),
        ("satisfied", "Satisfied"),
        ("neutral", "Neither satisfied or dissatisfied"),
        ("dissatisfied", "Dissatisfied"),
        ("very_dissatisfied", "Very dissatisfied"),
    ]

    # Below are fields corresponding to each question in your form:
    how_satisfied = models.CharField(
        max_length=50,
        help_text="How satisfied did you feel about the service?",
        blank=True,
        choices=SATISFACTION_CHOICES,
    )
    would_recommend = models.CharField(
        max_length=50,
        help_text="Would you recommend the service?",
        blank=True,
    )
    where_did_you_hear = models.CharField(
        max_length=255,
        help_text="Where did you hear about this service?",
        blank=True,
    )
    why_did_you_come = models.CharField(
        max_length=255,
        help_text="Why did you come to this site?",
        blank=True,
    )
    did_you_get_what_you_wanted = models.CharField(
        max_length=100, help_text="Did you get what you wanted?", blank=True
    )
    improve_our_service = models.TextField(
        help_text="How can we improve our service?", blank=True
    )

    submitted_at = models.DateTimeField(auto_now_add=True)

    content_panels = Page.content_panels + [
        FieldPanel("user_ref"),
        FieldPanel("how_satisfied"),
        FieldPanel("would_recommend"),
        FieldPanel("where_did_you_hear"),
        FieldPanel("why_did_you_come"),
        FieldPanel("did_you_get_what_you_wanted"),
        FieldPanel("improve_our_service"),
    ]

    def __str__(self):
        return f"Feedback from {self.user_ref} - {self.submitted_at}"
