import json
import logging
import boto3
from botocore.exceptions import NoRegionError, NoCredentialsError
from functools import wraps

from django.db.models.signals import post_save
from django.dispatch import receiver

from core.utils.check_product_required_fields_aps_decorator import (
    check_required_event_fields,
)
from configs.get_secret_config import Config
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

config = Config()
logger = logging.getLogger(__name__)
MISSING_STATUS_WARNING = "Missing or invalid status for product %s"

# Initialize AWS EventBridge client (or simulate if unavailable)
try:
    eventbridge = boto3.client("events")
    aws_access = True
except (NoRegionError, NoCredentialsError) as e:
    logger.warning("AWS access is unavailable: %s", e)
    aws_access = False

STATUS_MAPPING = {
    "live": "Live",
    "archived": "Archived",
    "withdrawn": "Withdrawn",
    "draft": "Draft",
}


def skip_if_suppressed(fn):
    """Skip handler if instance.suppress_event is True."""

    @wraps(fn)
    def wrapper(sender, instance, **kwargs):
        if getattr(instance, "suppress_event", False):
            logger.info(
                "Event suppressed for product %s (suppress_event=True)",
                instance.product_code,
            )
            return
        return fn(sender, instance, **kwargs)

    return wrapper


def prepare_product_data(product_instance, required_fields_enum, status):
    """
    Build the event payload for EventBridge, returning only the
    fields required for this status and avoiding NoneType errors.
    """
    normalised = STATUS_MAPPING.get(status, status)

    # ARCHIVED / WITHDRAWN: minimal payloads
    if status in ("archived", "withdrawn"):
        return {
            "publicationId": str(product_instance.product_code),
            "status": normalised,
        }

    # Need update_ref for draft/live
    update = getattr(product_instance, "update_ref", None)
    if not update and status != "draft":
        logger.error(
            "No update_ref for product %s when preparing %s payload",
            product_instance.product_code,
            status,
        )
        return {
            "publicationId": str(product_instance.product_code),
            "status": normalised,
        }

    # DRAFT: full draft payload
    if status == "draft":
        return {
            "publicationId": str(product_instance.product_code),
            "title": product_instance.product_title,
            "status": normalised,
            "maxOrder": [],
            "uom": getattr(update, "unit_of_measure", ""),
            "runToZero": getattr(update, "run_to_zero", False),
            "costCentre": "",
            "localCode": "",
            "client": client.client_name.value,
            "invoicingClient": invoicing_client.invoice_client.value,
            "productGroup": product_group.product_group_name.value,
            "minimumStockLevel": 0,
            "relatedArticle": "",
            "stockOwner": [],
            "stockReferral": [],
        }

    # LIVE (and any other non‐draft) statuses
    full = {
        "publicationId": str(product_instance.product_code),
        "title": product_instance.product_title,
        "status": normalised,
        "maxOrder": [
            {"companyKeys": ol.full_external_keys, "quantity": ol.order_limit}
            for ol in product_instance.order_limits.all()
        ],
        "uom": getattr(update, "unit_of_measure", ""),
        "runToZero": getattr(update, "run_to_zero", False),
        "costCentre": getattr(update, "cost_centre", ""),
        "localCode": getattr(update, "local_code", ""),
        "client": client.client_name.value,
        "invoicingClient": invoicing_client.invoice_client.value,
        "productGroup": product_group.product_group_name.value,
        "minimumStockLevel": getattr(update, "minimum_stock_level", 0),
        "relatedArticle": product_instance.file_url,
        "stockOwner": [getattr(update, "stock_owner_email_address", "")],
        "stockReferral": [getattr(update, "order_referral_email_address", "")],
    }

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

    filtered = {
        field_mapping[f.value]: full[field_mapping[f.value]]
        for f in required_fields_enum
        if f.value in field_mapping and field_mapping[f.value] in full
    }

    # Always ensure these metadata fields
    filtered.update(
        {
            "client": client.client_name.value,
            "invoicingClient": invoicing_client.invoice_client.value,
            "productGroup": product_group.product_group_name.value,
        }
    )

    return filtered


def send_product_event(product_instance, event_type, detail_type, required_fields_enum):
    """Assemble and send (or simulate) an EventBridge event."""
    try:
        data = prepare_product_data(product_instance, required_fields_enum, event_type)
        payload = {"event_type": event_type, "product_data": data}
        logger.info("Prepared %s payload: %s", event_type, data)

        if aws_access:
            resp = eventbridge.put_events(
                Entries=[
                    {
                        "Source": config.get_hpub_event_bridge_source(),
                        "DetailType": detail_type,
                        "Detail": json.dumps(payload),
                        "EventBusName": config.get_hpub_event_bridge_bus_name(),
                    }
                ]
            )
            logger.info(
                "Sent %s event for %s: %s",
                event_type,
                product_instance.product_code,
                resp,
            )
        else:
            logger.info(
                "Simulated %s event for %s: %s",
                event_type,
                product_instance.product_code,
                payload,
            )

    except Exception as exc:
        logger.error(
            "Error sending %s event for %s: %s",
            event_type,
            product_instance.product_code,
            exc,
        )


# -- signals --


@receiver(post_save, sender=Product)
@skip_if_suppressed
@check_required_event_fields([f.value for f in required_event_fields_draft])
def send_product_draft_event(sender, instance, **kwargs):
    status = (instance.status or "").lower()
    logger.info("Draft hook: status=%r", status)
    if status == "draft":
        send_product_event(
            instance,
            "draft",
            config.get_hpub_event_bridge_detail_type_product_draft(),
            required_event_fields_draft,
        )
    else:
        logger.warning(MISSING_STATUS_WARNING, instance.product_code)


@receiver(post_save, sender=Product)
@skip_if_suppressed
@check_required_event_fields([f.value for f in required_event_fields_live])
def send_product_live_event(sender, instance, **kwargs):
    status = (instance.status or "").lower()
    logger.info("Live hook: status=%r", status)
    if status == "live":
        send_product_event(
            instance,
            "live",
            config.get_hpub_event_bridge_detail_type_product_live(),
            required_event_fields_live,
        )
    else:
        logger.warning(MISSING_STATUS_WARNING, instance.product_code)


@receiver(post_save, sender=Product)
@skip_if_suppressed
@check_required_event_fields([f.value for f in required_event_fields_archived])
def send_product_archived_event(sender, instance, **kwargs):
    status = (instance.status or "").lower()
    logger.info("Archived hook: status=%r", status)
    if status == "archived":
        send_product_event(
            instance,
            "archived",
            config.get_hpub_event_bridge_detail_type_product_archive(),
            required_event_fields_archived,
        )
    else:
        logger.warning(MISSING_STATUS_WARNING, instance.product_code)


@receiver(post_save, sender=Product)
@skip_if_suppressed
@check_required_event_fields([f.value for f in required_event_fields_withdrawn])
def send_product_withdrawn_event(sender, instance, **kwargs):
    status = (instance.status or "").lower()
    logger.info("Withdrawn hook: status=%r", status)
    if status == "withdrawn":
        send_product_event(
            instance,
            "withdrawn",
            config.get_hpub_event_bridge_detail_type_product_withdrawn(),
            required_event_fields_withdrawn,
        )
    else:
        logger.warning(MISSING_STATUS_WARNING, instance.product_code)
