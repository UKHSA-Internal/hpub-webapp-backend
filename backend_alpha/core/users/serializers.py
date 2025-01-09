import uuid

from core.establishments.models import Establishment
from core.establishments.serializers import EstablishmentSerializer
from core.organizations.serializers import OrganizationSerializer
from core.roles.models import Role
from core.roles.serializers import RoleSerializer
from rest_framework import serializers

from .models import User


class UserSerializer(serializers.ModelSerializer):
    establishment_ref = EstablishmentSerializer(read_only=True)
    organization_ref = OrganizationSerializer(read_only=True)
    role_ref = RoleSerializer(read_only=True)

    establishment_id = serializers.PrimaryKeyRelatedField(
        queryset=Establishment.objects.all(),
        source="establishment_ref",
        write_only=True,
    )

    role_name = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            "user_id",
            "email",
            "mobile_number",
            "first_name",
            "last_name",
            "is_authorized",
            "last_login",
            "establishment_id",
            "organization_ref",
            "role_name",
            "role_ref",
            "password",
            "created_at",
            "updated_at",
            "email_verified",
            "establishment_ref",
        ]
        extra_kwargs = {
            "password": {"write_only": True},
            "is_authorized": {"read_only": True},
            "email_verified": {"read_only": True},
            "organization_ref": {"read_only": True},
            "last_login": {"read_only": True},
        }

    def create(self, validated_data):

        # Extract role_name from validated_data
        role_name = validated_data.pop("role_name", None)

        if role_name:
            role = Role.objects.filter(name=role_name).first()
            if role:
                validated_data["role_ref"] = role
        # Check if the 'user_id' is provided in the request
        user_id = validated_data.get("user_id", None)
        if not user_id:
            validated_data["user_id"] = str(
                uuid.uuid4()
            )  # Generate a UUID if no id is provided
        return super().create(validated_data)
