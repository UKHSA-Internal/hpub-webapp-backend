from rest_framework import serializers

from .models import AnalyticsKPI


class AnalyticsKPISerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticsKPI
        fields = [
            "kpi_id",
            "year",
            "month",
            "user_satisfaction_score",
            "digital_take_up_percentage",
            "cost_per_transaction",
            "order_completion_rate_percentage",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["kpi_id", "created_at", "updated_at"]
