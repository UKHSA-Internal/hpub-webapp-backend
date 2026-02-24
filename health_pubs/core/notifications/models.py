import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class NotificationState(models.TextChoices):
    ENABLED = "ENABLED"
    SCHEDULED = "SCHEDULED"
    DISABLED = "DISABLED"


class Notification(models.Model):
    notification_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=225,
    )
    is_enabled = models.BooleanField(default=False)
    message = models.TextField(blank=True)
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def clean(self):
        if self.start_at and self.end_at and self.start_at >= self.end_at:
            raise ValidationError({"end_at": "end_at must be after start_at."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def state(self):
        now = timezone.now()

        if not self.is_enabled:
            return NotificationState.DISABLED

        if self.start_at and now < self.start_at:
            return NotificationState.SCHEDULED

        if self.end_at and now > self.end_at:
            return NotificationState.DISABLED

        return NotificationState.ENABLED
