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
    help = "Find draft products with missing fields and publish_date within the next 7 days."

    @singleton_cron(lock_id=20250417)
    def handle(self, *args, **options):
        today = timezone.now().date()
        deadline = today + timedelta(days=7)

        # Drafts scheduled to go live in the next 7 days
        qs = Product.objects.filter(
            status="draft",
            publish_date__range=(today, deadline),
        )

        checker = ProductStatusUpdateView()
        incomplete = []

        for product in qs:
            missing = checker.check_required_fields(product)
            if missing:
                incomplete.append(
                    {
                        "tag": product.tag,
                        "product_title": product.product_title,
                        "product_code": product.product_code,
                    }
                )
                logger.info(
                    f"Draft product '{product.product_title}' "
                    f"({product.product_code}) missing: {missing}"
                )

        payload = json.dumps(incomplete)
        logger.info(f"Found {len(incomplete)} incomplete draft(s) within 7 days.")
        self.stdout.write(self.style.SUCCESS(payload))
