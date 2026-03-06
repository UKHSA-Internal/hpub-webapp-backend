import uuid

from rest_framework import serializers

from .models import WhereToUse


class WhereToUseSerializer(serializers.ModelSerializer):
    class Meta:
        model = WhereToUse
        fields = ["where_to_use_id", "name", "description", "key"]

    def create(self, validated_data):
        # Check if the 'where_to_use_id' is provided in the request
        where_to_use_id = validated_data.get("where_to_use_id", None)
        if not where_to_use_id:
            validated_data[
                "where_to_use_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)
