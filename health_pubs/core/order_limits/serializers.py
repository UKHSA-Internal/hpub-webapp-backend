import uuid

from core.establishments.serializers import EstablishmentSerializer
from core.organizations.serializers import OrganizationSerializer
from rest_framework import serializers

from .models import OrderLimitPage


class OrderLimitPageSerializer(serializers.ModelSerializer):
    organization = OrganizationSerializer(source="organization_ref", read_only=True)
    establishments = serializers.SerializerMethodField()
    full_external_keys = serializers.ListField(
        child=serializers.CharField(max_length=255), read_only=True
    )

    class Meta:
        model = OrderLimitPage
        fields = [
            "order_limit_id",
            "order_limit",
            "product_ref",
            "organization",
            "establishments",
            "full_external_keys",
        ]

    def get_establishments(self, obj):
        # Fetch establishments related to the organization
        organization = obj.organization_ref
        if organization:
            establishments = organization.establishments.all()
            return EstablishmentSerializer(establishments, many=True).data
        return []

    def create(self, validated_data):
        # Check if the 'order_limit_id' is provided in the request
        order_limit_id = validated_data.get("order_limit_id", None)
        if not order_limit_id:
            validated_data[
                "order_limit_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)
