import json
import logging
import boto3
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

logger = logging.getLogger(__name__)
config = Config()

try:
    eventbridge = boto3.client("events")
    aws_access = True
except Exception as e:
    logger.warning("AWS unavailable: %s", e)
    aws_access = False


STATUS_MAPPING = {
    "live": "Live",
    "archived": "Archived",
    "withdrawn": "Withdrawn",
    "draft": "Draft",
}


def skip_if_suppressed(fn):
    @wraps(fn)
    def wrapper(sender, instance, **kwargs):
        if getattr(instance, "suppress_event", False):
            logger.info("Event suppressed for %s", instance.product_code)
            return
        return fn(sender, instance, **kwargs)

    return wrapper


def build_max_order_from_order_limits(product_instance):
    """
    Build maxOrder array from OrderLimitPage objects, skipping any entries
    that have no companyKeys (empty full_external_keys).

    Also deduplicates on (companyKeys, quantity) to avoid repeated rows.
    """
    max_order = []
    seen = set()

    for ol in product_instance.order_limits.all():
        # Normalise keys to a clean list
        keys = list(ol.full_external_keys or [])
        # Skip if empty
        if not keys:
            continue

        # Optionally dedupe identical rows (same key set + quantity)
        key_tuple = tuple(sorted(keys))
        sig = (key_tuple, ol.order_limit)
        if sig in seen:
            continue
        seen.add(sig)

        max_order.append(
            {
                "companyKeys": keys,
                "quantity": ol.order_limit,
            }
        )

    return max_order


def prepare_product_data(product_instance, required_fields_enum, status):
    update = getattr(product_instance, "update_ref", None)
    normalised = STATUS_MAPPING.get(status, status)
    max_order = build_max_order_from_order_limits(product_instance)

    # Minimal for archived/withdrawn
    if status in ("archived", "withdrawn"):
        return {
            "publicationId": str(product_instance.product_code),
            "status": normalised,
        }

    getattr(update, "product_type", "") or ""
    uom = getattr(update, "unit_of_measure", None)

    # DRAFT PAYLOAD
    if status == "draft":
        return {
            "publicationId": product_instance.product_code,
            "title": product_instance.product_title,
            "status": normalised,
            "maxOrder": [],
            "uom": uom,
            "runToZero": getattr(update, "run_to_zero", False),
            "costCentre": "",
            "localCode": "",
            "client": client.client_name.value,
            "invoicingClient": invoicing_client.invoice_client.value,
            "productGroup": product_group.product_group_name.value,
            "minimumStockLevel": 0,
            "relatedArticle": "",
            "stockOwner": [getattr(update, "stock_owner_email_address", "")],
            "stockReferral": [getattr(update, "order_referral_email_address", "")],
        }

    # LIVE PAYLOAD
    full = {
        "publicationId": product_instance.product_code,
        "title": product_instance.product_title,
        "status": normalised,
        "languageName": product_instance.language_name,
        "maxOrder": max_order,
        "uom": uom,
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

    return full


def send_product_event(product_instance, event_type, detail_type, required_fields_enum):
    payload = prepare_product_data(product_instance, required_fields_enum, event_type)
    logger.info("Prepared %s payload: %s", event_type, payload)

    if not aws_access:
        logger.info("Simulated %s event", event_type)
        return

    try:
        eventbridge.put_events(
            Entries=[
                {
                    "Source": config.get_hpub_event_bridge_source(),
                    "DetailType": detail_type,
                    "Detail": json.dumps(
                        {"event_type": event_type, "product_data": payload}
                    ),
                    "EventBusName": config.get_hpub_event_bridge_bus_name(),
                }
            ]
        )
        logger.info("Sent %s event for %s", event_type, product_instance.product_code)
    except Exception as e:
        logger.error("Error sending %s: %s", event_type, e)


# -------------------------------------------------------------------
# SIGNAL HANDLERS — FIXED
# -------------------------------------------------------------------


@receiver(post_save, sender=Product)
@skip_if_suppressed
@check_required_event_fields([f.value for f in required_event_fields_draft])
def send_product_draft_event(sender, instance, **kwargs):
    instance.refresh_from_db()
    if instance.update_ref:
        instance.update_ref.refresh_from_db()

    if (instance.status or "").lower() == "draft":
        send_product_event(
            instance,
            "draft",
            config.get_hpub_event_bridge_detail_type_product_draft(),
            required_event_fields_draft,
        )


@receiver(post_save, sender=Product)
@skip_if_suppressed
@check_required_event_fields([f.value for f in required_event_fields_live])
def send_product_live_event(sender, instance, **kwargs):
    instance.refresh_from_db()
    if instance.update_ref:
        instance.update_ref.refresh_from_db()

    if (instance.status or "").lower() == "live":
        send_product_event(
            instance,
            "live",
            config.get_hpub_event_bridge_detail_type_product_live(),
            required_event_fields_live,
        )


@receiver(post_save, sender=Product)
@skip_if_suppressed
@check_required_event_fields([f.value for f in required_event_fields_archived])
def send_product_archived_event(sender, instance, **kwargs):
    instance.refresh_from_db()
    if instance.update_ref:
        instance.update_ref.refresh_from_db()

    if (instance.status or "").lower() == "archived":
        send_product_event(
            instance,
            "archived",
            config.get_hpub_event_bridge_detail_type_product_archive(),
            required_event_fields_archived,
        )


@receiver(post_save, sender=Product)
@skip_if_suppressed
@check_required_event_fields([f.value for f in required_event_fields_withdrawn])
def send_product_withdrawn_event(sender, instance, **kwargs):
    instance.refresh_from_db()
    if instance.update_ref:
        instance.update_ref.refresh_from_db()

    if (instance.status or "").lower() == "withdrawn":
        send_product_event(
            instance,
            "withdrawn",
            config.get_hpub_event_bridge_detail_type_product_withdrawn(),
            required_event_fields_withdrawn,
        )
