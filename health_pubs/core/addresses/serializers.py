import uuid

from core.users.models import User
from core.users.serializers import UserSerializer
from rest_framework import serializers

from .models import Address


class AddressSerializer(serializers.ModelSerializer):
    address_id = serializers.CharField(read_only=True)
    address_line1 = serializers.CharField(required=True)
    address_line2 = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    address_line3 = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    city = serializers.CharField(required=True)
    county = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    postcode = serializers.CharField(required=True)
    country = serializers.CharField(required=True)
    is_default = serializers.BooleanField(required=False)
    verified = serializers.BooleanField(required=False)
    user_ref = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), required=True, allow_null=True
    )

    user_info = serializers.SerializerMethodField()

    class Meta:
        model = Address
        fields = [
            "address_id",
            "user_ref",
            "address_line1",
            "address_line2",
            "address_line3",
            "city",
            "county",
            "postcode",
            "country",
            "is_default",
            "verified",
            "user_info",
        ]

    def create(self, validated_data):
        # Check if the 'address_id' is provided in the request
        address_id = validated_data.get("address_id", None)
        if not address_id:
            validated_data[
                "address_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)

    def get_user_info(self, obj):
        request = self.context.get("request", None)
        # Only return full user info if the requesting user's role is "admin"
        if (
            request
            and hasattr(request, "user")
            and getattr(request.user, "rol_ref", None)
            and request.user.rol_ref.name.lower() == "admin"
        ):
            return UserSerializer(obj.user_ref).data
        return None

    def validate(self, data):
        required_fields = ["address_line1", "city", "postcode", "country"]
        for field in required_fields:
            if not data.get(field):
                raise serializers.ValidationError(
                    {field: f"{field.replace('_', ' ').capitalize()} is required"}
                )
        return data
