import logging
import json
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.products.models import Product
from core.products.views import ProductStatusUpdateView
from core.utils.cron_lock import singleton_cron

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Find draft products with missing required fields and a publish_date between tomorrow and 7 days from now."

    @singleton_cron(lock_id=20250417)
    def handle(self, *args, **options):
        incomplete = self._collect_incomplete_drafts()
        self._output_results(incomplete)

    def _collect_incomplete_drafts(self):
        """Return a list of dicts for drafts missing required fields,
        scheduled to publish > today and ≤ 7 days from now."""
        today = timezone.now().date()
        deadline = today + timedelta(days=7)

        drafts = Product.objects.filter(
            status="draft",
            publish_date__gt=today,
            publish_date__lte=deadline,
        )

        checker = ProductStatusUpdateView()
        incomplete = []

        for product in drafts:
            missing_fields = checker.check_required_fields(product)
            if not missing_fields:
                continue

            logger.info(
                "Draft product '%s' (%s) missing: %s",
                product.product_title,
                product.product_code,
                missing_fields,
            )
            incomplete.append(
                {
                    "tag": product.tag,
                    "product_title": product.product_title,
                    "product_code": product.product_code,
                }
            )

        return incomplete

    def _output_results(self, incomplete):
        count = len(incomplete)
        logger.info("Found %d incomplete draft(s) in the next 7 days.", count)

        payload = json.dumps(incomplete)
        if count:
            self.stdout.write(self.style.WARNING(payload))
        else:
            self.stdout.write(self.style.SUCCESS("No incomplete drafts found."))
