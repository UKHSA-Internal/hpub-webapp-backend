import uuid

from core.organizations.models import Organization
from rest_framework import serializers

from .models import Establishment


class EstablishmentSerializer(serializers.ModelSerializer):
    organization_ref = serializers.PrimaryKeyRelatedField(
        queryset=Organization.objects.all(), required=False
    )

    class Meta:
        model = Establishment
        fields = [
            "establishment_id",
            "organization_ref",
            "name",
            "external_key",
            "full_external_key",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        # Check if the 'establishment_id' is provided in the request
        establishment_id = validated_data.get("establishment_id", None)
        if not establishment_id:
            validated_data["establishment_id"] = uuid.uuid4()
        return super().create(validated_data)
