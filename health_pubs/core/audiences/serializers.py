import uuid

from rest_framework import serializers

from .models import Audience


class AudienceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Audience
        fields = ["audience_id", "name", "description", "key"]

    def create(self, validated_data):
        # Check if the 'audience_id' is provided in the request
        audience_id = validated_data.get("audience_id", None)
        if not audience_id:
            validated_data["audience_id"] = uuid.uuid4()
        return super().create(validated_data)
