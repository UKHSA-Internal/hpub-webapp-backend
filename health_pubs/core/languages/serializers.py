import uuid

from rest_framework import serializers

from .models import LanguagePage


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = LanguagePage
        fields = ["language_id", "language_names", "iso_language_code"]

    def create(self, validated_data):
        # Check if the 'language_id' is provided in the request
        language_id = validated_data.get("language_id", None)
        if not language_id:
            validated_data[
                "language_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)
