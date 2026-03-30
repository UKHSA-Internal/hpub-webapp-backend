import uuid

from django.template.defaultfilters import slugify
from django.contrib.contenttypes.models import ContentType
from rest_framework import serializers

from core.establishments.models import Establishment
from core.establishments.serializers import EstablishmentSerializer
from core.organizations.serializers import OrganizationSerializer
from core.roles.models import Role
from core.roles.serializers import RoleSerializer
from core.organizations.models import Organization
from core.establishments.models import Establishment
from core.users.models import User


class UserSerializer(serializers.ModelSerializer):
    # UserResponse
    establishment_ref = EstablishmentSerializer(read_only=True)
    organization_ref = OrganizationSerializer(read_only=True)
    role_ref = RoleSerializer(read_only=True)

    # UserRequest
    establishment_name = serializers.CharField(write_only=True)
    organization_name = serializers.CharField(write_only=True)
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
            "password",
            "created_at",
            "updated_at",
            "email_verified",
            "role_name",
            "organization_name",
            "establishment_name",
            "role_ref",
            "organization_ref",
            "establishment_ref",
        ]
        extra_kwargs = {
            "password": {"write_only": True},
            "is_authorized": {"read_only": True},
            "email_verified": {"read_only": True},
            "organization_ref": {"read_only": True},
            "last_login": {"read_only": True},
        }

    def validate(self, attrs):
        # Get read-only fields from serializer Meta
        read_only_fields = {
            field_name for field_name, field in self.fields.items() if field.read_only
        }

        # Check if any read-only fields were sent in the request
        invalid = read_only_fields.intersection(self.initial_data.keys())

        if invalid:
            raise serializers.ValidationError(
                {
                    "errors": [
                        {
                            "error": "ValidationError",
                            "description": f"{field} is read-only.",
                        }
                        for field in invalid
                    ]
                }
            )

        return super().validate(attrs)

    def to_model(self):
        # Get role_ref from role_name
        name = self.validated_data.pop("role_name", None)
        if name:
            try:
                self.validated_data["role_ref"] = Role.objects.get(name=name)
            except Role.DoesNotExist:
                raise serializers.ValidationError(
                    {"role_name": [f"Role '{name}' does not exist."]}
                )

        # Get organization_ref from organization_name
        name = self.validated_data.pop("organization_name", None)
        if name:
            try:
                self.validated_data["organization_ref"] = Organization.objects.get(
                    name=name
                )
            except Organization.DoesNotExist:
                raise serializers.ValidationError(
                    {"organization_name": [f"Organization '{name}' does not exist."]}
                )

        # Get establishment_ref from establishment_name
        name = self.validated_data.pop("establishment_name", None)
        if name:
            try:
                self.validated_data["establishment_ref"] = Establishment.objects.get(
                    name=name
                )
            except Establishment.DoesNotExist:
                raise serializers.ValidationError(
                    {"establishment_name": [f"Establishment '{name}' does not exist."]}
                )

        # Check if the 'user_id' is provided in the request
        user_id = self.validated_data.get("user_id", None)
        if not user_id:
            self.validated_data["user_id"] = str(
                uuid.uuid4()
            )  # Generate a UUID if no id is provided

        self.validated_data["title"] = f"User {self.validated_data['first_name']}"
        self.validated_data["slug"] = slugify(
            f"user-{self.validated_data['email']}-{self.validated_data['user_id']}"
        )
        self.validated_data["content_type"] = ContentType.objects.get_for_model(User)
        return User(**self.validated_data)
