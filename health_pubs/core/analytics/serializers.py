from rest_framework import serializers

from .models import AnalyticsKPI


class AnalyticsKPISerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticsKPI
        fields = [
            "kpi_id",
            "period",
            "website_visits_sum",
            "feedback_form_submissions",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["kpi_id", "created_at", "updated_at"]
