import uuid
from rest_framework import serializers
from .models import EventAnalytics


class AnalyticsEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = EventAnalytics
        fields = [
            "event_analytics_id",
            "event_type",
            "session_id",
            "timestamp",
            "metadata",
            "user_ref",
        ]
        read_only_fields = ["event_analytics_id", "timestamp"]

    def create(self, validated_data):
        # Check if the 'event_analytics_id' is provided in the request
        event_analytics_id = validated_data.get("event_analytics_id", None)
        if not event_analytics_id:
            validated_data[
                "event_analytics_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)
