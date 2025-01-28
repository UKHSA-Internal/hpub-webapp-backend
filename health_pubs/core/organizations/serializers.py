import uuid

from rest_framework import serializers

from .models import Organization


class OrganizationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ["organization_id", "name", "external_key", "created_at", "updated_at"]

    def create(self, validated_data):
        # Check if the 'organization_id' is provided in the request
        organization_id = validated_data.get("organization_id", None)
        if not organization_id:
            validated_data[
                "organization_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)
