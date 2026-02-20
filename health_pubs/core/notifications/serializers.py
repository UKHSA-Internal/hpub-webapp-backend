from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    # Derived from model logic; not saved in the database.
    state = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "notification_id",
            "is_enabled",
            "state",
            "message",
            "start_at",
            "end_at",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["notification_id", "state", "created_at", "updated_at"]

    def to_internal_value(self, data):
        # Accept L2/L3 team field names and map them to normal backend field names.
        payload = data.copy() if hasattr(data, "copy") else dict(data)
        aliases = {
            "HPUB_NOTIFICATION_ENABLED": "is_enabled",
            "HPUB_NOTIFICATION_MESSAGE": "message",
            "HPUB_NOTIFICATION_START": "start_at",
            "HPUB_NOTIFICATION_END": "end_at",
        }
        for alias, field_name in aliases.items():
            if alias in payload and field_name in payload and payload[alias] != payload[field_name]:
                raise serializers.ValidationError(
                    {alias: f"Conflicts with {field_name}."}
                )
            if alias in payload and field_name not in payload:
                payload[field_name] = payload.get(alias)
        return super().to_internal_value(payload)

    def validate(self, attrs):
        # Validate the effective time window for both create and update.
        start_at = attrs.get("start_at")
        end_at = attrs.get("end_at")

        if self.instance:
            if "start_at" not in attrs:
                start_at = self.instance.start_at
            if "end_at" not in attrs:
                end_at = self.instance.end_at

        if start_at and end_at and start_at >= end_at:
            raise serializers.ValidationError(
                {"end_at": "end_at must be after start_at."}
            )

        return attrs

    def get_state(self, obj):
        return obj.state


class NotificationEnabledSerializer(serializers.Serializer):
    # Used by /notifications/{id}/enabled/ to toggle the is_enabled flag.
    is_enabled = serializers.BooleanField()

    def to_internal_value(self, data):
        # Accept L2/L3 team field name and map it to the normal backend field name.
        payload = data.copy() if hasattr(data, "copy") else dict(data)
        if (
            "HPUB_NOTIFICATION_ENABLED" in payload
            and "is_enabled" in payload
            and payload["HPUB_NOTIFICATION_ENABLED"] != payload["is_enabled"]
        ):
            raise serializers.ValidationError(
                {"HPUB_NOTIFICATION_ENABLED": "Conflicts with is_enabled."}
            )
        if "HPUB_NOTIFICATION_ENABLED" in payload and "is_enabled" not in payload:
            payload["is_enabled"] = payload.get("HPUB_NOTIFICATION_ENABLED")
        return super().to_internal_value(payload)
