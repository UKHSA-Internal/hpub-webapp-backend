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
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    user_satisfaction_score = models.CharField(max_length=50)
    digital_take_up_percentage = models.CharField(max_length=50)
    cost_per_transaction = models.CharField(max_length=50)
    order_completion_rate_percentage = models.CharField(max_length=50)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["year", "month"]
        constraints = [
            models.UniqueConstraint(
                fields=["year", "month"],
                name="unique_analytics_kpi_year_month",
            )
        ]
