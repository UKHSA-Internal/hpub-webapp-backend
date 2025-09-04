import json
import logging

import boto3
from botocore.exceptions import NoRegionError, NoCredentialsError
from core.utils.check_order_required_fields_aps_decorator import (
    check_required_order_fields,
)
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from configs.get_secret_config import Config

from .models import Order

config = Config()

logger = logging.getLogger(__name__)

# Check if AWS access is available
try:
    eventbridge = boto3.client("events")
    aws_access = True
except (NoRegionError, NoCredentialsError) as e:
    logger.warning(f"AWS access is unavailable: {e}")
    aws_access = False

required_fields = [
    "order_id",
    "user_ref",
    "address_ref",
    "full_external_key",
    "order_items",
]


@receiver(post_save, sender=Order)
def send_order_to_eventbridge(sender, instance, created, **kwargs):
    if created:
        logger.info(f"Order {instance.id} creation detected, preparing to send event.")
        try:
            transaction.on_commit(lambda: send_event(instance))
        except Exception as e:
            logger.error(
                f"Error during transaction commit for order {instance.id}: {e}"
            )


@check_required_order_fields(required_fields)
def send_event(order_instance):
    """Send the order event to EventBridge."""
    try:
        # Prepare event detail (as required by APS)
        order_data = prepare_order_data(order_instance)
        event_detail = {"event_type": "order-placed", "order_data": order_data}
        logger.info("Order Data: %s", order_data)

        if aws_access:
            # Send event to EventBridge
            response = eventbridge.put_events(
                Entries=[
                    {
                        "Source": str(config.get_hpub_event_bridge_source()),
                        "DetailType": str(
                            config.get_hpub_event_bridge_detail_type_order_creation()
                        ),
                        "Detail": json.dumps(event_detail),
                        "EventBusName": str(config.get_hpub_event_bridge_bus_name()),
                    }
                ]
            )
            # Logging response from EventBridge
            logger.info(
                f"Order {order_instance.order_id} sent to EventBridge: {response}"
            )
        else:
            # Simulate a successful EventBridge response for testing
            logger.info(
                f"Simulated EventBridge event for Order {order_instance.order_id}: {json.dumps(event_detail)}"
            )

    except Exception as e:
        logger.error(
            f"Error sending order {order_instance.order_id} to EventBridge: {e}"
        )


def prepare_order_data(order_instance):
    """
    Prepares the order data in a format to send to EventBridge.
    """
    user_instance = order_instance.user_ref
    address_instance = order_instance.address_ref

    order_items = order_instance.order_items.all()

    user_info = {
        "email": user_instance.email,
        "mobile_number": user_instance.mobile_number,
        "organization_ref": user_instance.organization_ref,
    }

    address = {
        "address_lines": [
            address_instance.address_line1,
            address_instance.address_line2,
            address_instance.address_line3,
        ],
        "city": address_instance.city,
        "county": address_instance.county,
        "postcode": address_instance.postcode,
        "country": address_instance.country,
    }

    order_data = {
        "orderReference": str(order_instance.order_id),
        "purchaseOrderNo": str(order_instance.order_confirmation_number),
        "deliveryContactFullName": f"{user_instance.first_name} {user_instance.last_name}",
        "deliveryContactEmail": user_info.get("email"),
        "deliveryContactPhone": user_info.get("mobile_number", ""),
        "deliveryContactFullAddress": {
            "addressLines": address["address_lines"],
            "city": address.get("city", ""),
            "county": address.get("county", ""),
            "postcode": address.get("postcode", ""),
            "country": address.get("country", "England"),
        },
        "companyKey": order_instance.full_external_key,
        "items": [
            {"publicationId": item.product_ref.product_code, "quantity": item.quantity}
            for item in order_items
        ],
    }

    return order_data
