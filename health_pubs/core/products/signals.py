import json
import logging
import boto3
from botocore.exceptions import NoRegionError, NoCredentialsError
from core.utils.check_product_required_fields_aps_decorator import (
    check_required_event_fields,
)
from django.db.models.signals import post_save
from django.dispatch import receiver

from .enums import (
    client,
    invoicing_client,
    product_group,
    required_event_fields_archived,
    required_event_fields_draft,
    required_event_fields_live,
    required_event_fields_withdrawn,
)
from .models import Product
from configs.get_secret_config import Config

config = Config()

logger = logging.getLogger(__name__)

# Check AWS access and initialize EventBridge client
try:
    eventbridge = boto3.client("events")
    aws_access = True
except (NoRegionError, NoCredentialsError) as e:
    logger.warning(f"AWS access is unavailable: {e}")
    aws_access = False

# Define status mapping to ensure correct capitalization
STATUS_MAPPING = {
    "live": "Live",
    "archived": "Archived",
    "withdrawn": "Withdrawn",
    "draft": "Draft",
}


def prepare_product_data(product_instance, required_fields_enum, status):
    """
    Prepares the product data in a format to send to EventBridge,
    keeping the correct keys and including the required fields.
    """
    update_instance = product_instance.update_ref

    # Map the product data to the expected keys
    product_data = {
        "publicationId": str(product_instance.product_code),
        "title": product_instance.product_title,
        "status": STATUS_MAPPING.get(status, status),
        "maxOrder": [
            {
                "companyKeys": order_limit.full_external_keys,
                "quantity": order_limit.order_limit,
            }
            for order_limit in product_instance.order_limits.all()
        ],
        "uom": update_instance.unit_of_measure,
        "runToZero": update_instance.run_to_zero,
        "costCentre": update_instance.cost_centre,
        "localCode": update_instance.local_code,
        "client": client.client_name.value,
        "invoicingClient": invoicing_client.invoice_client.value,
        "productGroup": product_group.product_group_name.value,
        "minimumStockLevel": update_instance.minimum_stock_level,
        "relatedArticle": product_instance.file_url,
        "stockOwner": [
            update_instance.stock_owner_email_address,
        ],
        "stockReferral": [
            update_instance.order_referral_email_address,
        ],
    }

    # Mapping from required_fields_enum keys to product_data keys
    field_mapping = {
        "product_code": "publicationId",
        "product_title": "title",
        "status": "status",
        "order_limits": "maxOrder",
        "unit_of_measure": "uom",
        "run_to_zero": "runToZero",
        "cost_centre": "costCentre",
        "local_code": "localCode",
        "client": "client",
        "invoicing_client": "invoicingClient",
        "product_group": "productGroup",
        "minimum_stock_level": "minimumStockLevel",
        "file_url": "relatedArticle",
        "stock_owner_email_address": "stockOwner",
        "order_referral_email_address": "stockReferral",
    }

    # Filter product_data to only include the required fields
    filtered_product_data = {
        field_mapping[field.value]: product_data[field_mapping[field.value]]
        for field in required_fields_enum
        if field.value in field_mapping and field_mapping[field.value] in product_data
    }

    return filtered_product_data


def send_product_event(product_instance, event_type, detail_type, required_fields_enum):
    """
    Send the product event to EventBridge.
    """
    try:
        # Prepare event detail
        product_data = prepare_product_data(
            product_instance, required_fields_enum, event_type
        )
        event_detail = {"event_type": event_type, "product_data": product_data}
        logger.info("Product Data: %s", product_data)

        if aws_access:
            # Send event to EventBridge
            response = eventbridge.put_events(
                Entries=[
                    {
                        "Source": config.get_hpub_event_bridge_source,
                        "DetailType": detail_type,
                        "Detail": json.dumps(event_detail),
                        "EventBusName": config.get_hpub_event_bridge_bus_name,
                    }
                ]
            )
            # Log response from EventBridge
            logger.info(
                f"Product {product_instance.product_code} event sent to EventBridge: {response}"
            )
        else:
            # Simulate a successful EventBridge response for testing
            logger.info(
                f"Simulated EventBridge event for Product {product_instance.product_code}: {json.dumps(event_detail)}"
            )

    except Exception as e:
        logger.error(
            f"Error sending product {product_instance.product_code} event to EventBridge: {e}"
        )


# Signals for different product statuses


@receiver(post_save, sender=Product)
@check_required_event_fields([field.value for field in required_event_fields_draft])
def send_product_draft_event(sender, instance, **kwargs):
    """
    Signal to send a draft product event if the status is 'draft'.
    """
    if instance.status == "draft":
        send_product_event(
            instance,
            "draft",
            config.get_hpub_event_bridge_detail_type_product_draft,
            required_event_fields_draft,
        )


@receiver(post_save, sender=Product)
@check_required_event_fields([field.value for field in required_event_fields_live])
def send_product_live_event(sender, instance, **kwargs):
    """
    Signal to send a live product event if the status is 'live'.
    """
    if instance.status == "live":
        send_product_event(
            instance,
            "live",
            config.get_hpub_event_bridge_detail_type_product_live,
            required_event_fields_live,
        )


@receiver(post_save, sender=Product)
@check_required_event_fields([field.value for field in required_event_fields_archived])
def send_product_archived_event(sender, instance, **kwargs):
    """
    Signal to send an archived product event if the status is 'archived'.
    """
    if instance.status == "archived":
        send_product_event(
            instance, "archived", config.get_hpub_event_bridge_detail_type_product_archive, required_event_fields_archived
        )


@receiver(post_save, sender=Product)
@check_required_event_fields([field.value for field in required_event_fields_withdrawn])
def send_product_withdrawn_event(sender, instance, **kwargs):
    """
    Signal to send a withdrawn product event if the status is 'withdrawn'.
    """
    if instance.status == "withdrawn":
        send_product_event(
            instance,
            "withdrawn",
            config.get_hpub_event_bridge_detail_type_product_withdrawn,
            required_event_fields_withdrawn,
        )
