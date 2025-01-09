import uuid

from rest_framework import serializers

from .models import CustomerSupport


class CustomerSupportSerializer(serializers.ModelSerializer):
    message = serializers.CharField(max_length=500)
    
    class Meta:
        model = CustomerSupport
        fields = [
            "customer_support_id",
            "user_ref",
            "message",
            "summary",
            "contact_email",
            "contact_name",
            "created_at",
        ]

    def create(self, validated_data):
        # Check if the 'customer_support_id' is provided in the request
        customer_support_id = validated_data.get("customer_support_id", None)
        if not customer_support_id:
            validated_data["customer_support_id"] = uuid.uuid4()
        return super().create(validated_data)