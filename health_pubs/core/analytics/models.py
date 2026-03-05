import uuid

from django.db import models


class AnalyticsKPI(models.Model):
    kpi_id = models.CharField(
        primary_key=True,
        default=uuid.uuid4,
        unique=True,
        editable=False,
        max_length=36,
    )
    period = models.DateField(unique=True)
    website_visits_sum = models.PositiveIntegerField(default=0)
    feedback_form_submissions = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["period"]
