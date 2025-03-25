import uuid
from rest_framework import serializers

from core.users.serializers import UserSerializer
from .models import Feedback


class FeedbackSerializer(serializers.ModelSerializer):
    user_info = serializers.SerializerMethodField()

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
            "user_info",
        ]
        read_only_fields = ["feedback_id", "submitted_at", "user_info"]

    def get_user_info(self, obj):
        if obj.user_ref:  # Check if a user reference exists
            # Serialize and return user info
            return UserSerializer(obj.user_ref).data
        return None

    def create(self, validated_data):
        # If feedback_id wasn't provided, auto-generate
        if not validated_data.get("feedback_id"):
            validated_data["feedback_id"] = uuid.uuid4()
        return super().create(validated_data)
