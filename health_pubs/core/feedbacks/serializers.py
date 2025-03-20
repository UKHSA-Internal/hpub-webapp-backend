import uuid
from rest_framework import serializers
from .models import Feedback


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = [
            "feedback_id",
            "user_ref",
            "how_satisfied",
            "would_recommend",
            "where_did_you_hear",
            "why_did_you_come",
            "did_you_get_what_you_wanted",
            "improve_our_service",
            "submitted_at",
        ]

    def create(self, validated_data):
        # If feedback_id wasn't provided, auto-generate
        if not validated_data.get("feedback_id"):
            validated_data["feedback_id"] = uuid.uuid4()
        return super().create(validated_data)
