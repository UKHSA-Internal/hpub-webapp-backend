import uuid

from core.addresses.serializers import AddressSerializer
from core.users.serializers import UserSerializer
from rest_framework import serializers

from .models import Order, OrderItem


class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = [
            "order_item_id",
            "order_ref",
            "product_ref",
            "product_code",
            "quantity",
            "quantity_inprogress",
            "quantity_shipped",
            "quantity_cancelled",
        ]

    def create(self, validated_data):
        # Check if the 'order_item_id' is provided in the request
        order_item_id = validated_data.get("order_item_id", None)
        if not order_item_id:
            validated_data[
                "order_item_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)


class OrderSerializer(serializers.ModelSerializer):
    order_items = OrderItemSerializer(many=True, read_only=True)
    address = serializers.SerializerMethodField()
    user_info = serializers.SerializerMethodField()
    order_confirmation_number = serializers.CharField(read_only=True)
    order_origin = serializers.CharField(required=True)

    class Meta:
        model = Order
        fields = [
            "order_id",
            "user_ref",
            "order_date",
            "address",
            "created_at",
            "updated_at",
            "order_items",
            "tracking_number",
            "address_ref",
            "user_info",
            "order_confirmation_number",
            "order_origin",
            "full_external_key",
        ]

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

    def get_address(self, obj):
        if obj.address_ref:
            return AddressSerializer(obj.address_ref).data
        return None

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        # Include address details in the representation
        if instance.address_ref:
            representation["address"] = AddressSerializer(instance.address_ref).data
        # Include user details in the representation
        if instance.user_ref:
            representation["user_info"] = UserSerializer(instance.user_ref).data
        return representation

    def create(self, validated_data):
        # Check if the 'order_id' is provided in the request
        order_id = validated_data.get("order_id", None)
        if not order_id:
            validated_data[
                "order_id"
            ] = uuid.uuid4()  # Generate a UUID if no id is provided
        return super().create(validated_data)
