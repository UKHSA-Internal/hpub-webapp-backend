import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.cache import caches
from django.db import transaction
from core.products.models import Product
from core.products.serializers import ProductUpdateSerializer
from core.utils.cron_lock import singleton_cron

logger = logging.getLogger(__name__)


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


class Command(BaseCommand):
    help = "Publish all draft products whose publish_date is today at 00:00"

    def handle(self, *args, **options):
        today = timezone.localdate()
        drafts = Product.objects.filter(status="draft", publish_date=today)

        published, errors = [], {}
        for p in drafts:
            missing = _find_missing_fields(p)
            if missing:
                errors[p.product_code] = missing
                p.status = "error"
                p.is_scheduled_publish = False
                p.save(update_fields=["status", "is_scheduled_publish"])
                continue

            try:
                with transaction.atomic():
                    p.status = "live"
                    p.is_scheduled_publish = False
                    p.save(update_fields=["status", "is_scheduled_publish"])
                    published.append(p.product_code)
            except Exception as exc:
                logger.exception(f"Failed to publish {p.product_code}: {exc}")
                errors[p.product_code] = ["database_error"]
                p.status = "error"
                p.is_scheduled_publish = False
                p.save(update_fields=["status", "is_scheduled_publish"])

        # Clear the Django DB cache
        try:
            caches["default"].clear()
        except Exception:
            logger.exception("Failed to clear cache after publish job")

        logger.info(f"Published: {published}")
        if errors:
            logger.warning(f"Errors: {errors}")
