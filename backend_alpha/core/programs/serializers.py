import uuid

from rest_framework import serializers

from .models import Program


class ProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = Program
        fields = [
            "program_id",
            "programme_name",
            "is_featured",
            "is_temporary",
            "program_term",
            "external_key",
        ]
        read_only_fields = ["program_id"]

    def create(self, validated_data):
        # Check if the 'program_id' is provided in the request
        program_id = validated_data.get("program_id", None)
        if not program_id:
            validated_data["program_id"] = (
                uuid.uuid4()
            )  # Generate a UUID if no id is provided
        return super().create(validated_data)
