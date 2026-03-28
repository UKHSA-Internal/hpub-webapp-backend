import logging
from datetime import date
from typing import Dict, List, Optional, Tuple

from django.core.management.base import BaseCommand
from django.core.cache import caches
from django.db import transaction
from django.utils import timezone

from core.products.models import Product
from core.products.serializers import ProductUpdateSerializer
from core.utils.cron_lock import singleton_cron

from core.utils import logging_utils

logger = logging_utils.get_logger(__name__)


@singleton_cron(lock_id=20240415)
def _find_missing_fields(product):
    missing = []
    for f in ["product_title", "language_id", "program_id", "update_ref"]:
        if not getattr(product, f):
            missing.append(f)
    serializer = (
        ProductUpdateSerializer(product.update_ref, context={"tag": product.tag})
        if product.update_ref
        else ProductUpdateSerializer(context={"tag": product.tag})
    )
    for name, val in serializer.data.items():
        if val in (None, "", [], {}) and serializer.fields[name].required:
            missing.append(name)
    return missing


def run_scheduled_publish(
    today: Optional[date] = None,
) -> Tuple[List[str], Dict[str, List[str]]]:
    logger.info("publish_scheduled_products::handle")
    target_date = today or timezone.localdate()
    drafts = Product.objects.filter(
        status="draft",
        publish_date=target_date,
        is_scheduled_publish=True,
    )

    published: List[str] = []
    errors: Dict[str, List[str]] = {}
    for product in drafts:
        missing = _find_missing_fields(product)
        if missing:
            errors[product.product_code] = missing
            product.status = "error"
            product.is_scheduled_publish = False
            product.save(update_fields=["status", "is_scheduled_publish"])
            continue

        try:
            with transaction.atomic():
                product.status = "live"
                product.is_scheduled_publish = False
                product.save(update_fields=["status", "is_scheduled_publish"])
                published.append(product.product_code)
        except Exception as exc:
            logger.exception(f"Failed to publish {product.product_code}: {exc}")
            errors[product.product_code] = ["database_error"]
            product.status = "error"
            product.is_scheduled_publish = False
            product.save(update_fields=["status", "is_scheduled_publish"])

    try:
        caches["default"].clear()
    except Exception:
        logger.exception("Failed to clear cache after publish job")

    logger.info(f"Published: {published}")
    if errors:
        logger.warning(f"Errors: {errors}")

    return published, errors


class Command(BaseCommand):
    help = "Publish all draft products whose publish_date is today at 01:00"

    def handle(self, *args, **options):
        published, errors = run_scheduled_publish()
        self.stdout.write(
            self.style.SUCCESS(
                f"Published {len(published)} products; {len(errors)} products failed validation."
            )
        )
