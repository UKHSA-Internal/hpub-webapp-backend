import uuid

from rest_framework import serializers

from .models import Feedback


class FeedbackSerializer(serializers.ModelSerializer):
    class Meta:
        model = Feedback
        fields = ["feedback_id", "user_ref", "message", "submitted_at"]

    def create(self, validated_data):
        # Check if the 'feedback_id' is provided in the request
        feedback_id = validated_data.get("feedback_id", None)
        if not feedback_id:
            validated_data["feedback_id"] = uuid.uuid4()
        return super().create(validated_data)
