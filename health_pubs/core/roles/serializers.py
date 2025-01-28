import uuid

from rest_framework import serializers

from .models import Role


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ["role_id", "name", "permissions"]

    def create(self, validated_data):
        # Check if the 'role_id' is provided in the request
        role_id = validated_data.get("role_id", None)
        if not role_id:
            validated_data[
                "role_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)
