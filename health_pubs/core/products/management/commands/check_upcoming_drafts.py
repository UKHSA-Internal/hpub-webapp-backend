import logging
import json
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.products.models import Product
from core.products.views import ProductStatusUpdateView

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Check Draft products with incomplete fields and scheduled publish date within 7 days."

    def handle(self, *args, **kwargs):
        # Get the current date and the target date range
        current_date = timezone.now().date()
        target_date = current_date + timedelta(days=7)

        # Query products that are in Draft status and have a publish_date within the next 7 days
        products = Product.objects.filter(
            status="draft",
            publish_date__gte=current_date,
            publish_date__lte=target_date,
        )

        # Initialize the ProductStatusUpdateView for field checking
        status_update_view = ProductStatusUpdateView()

        incomplete_products = []

        # Iterate over the products and check for incomplete fields
        for product in products:
            missing_fields = status_update_view.check_required_fields(product)

            # If there are missing fields, append the product to the list
            if missing_fields:
                incomplete_products.append(
                    {
                        "product_title": product.product_title,
                        "product_code": product.product_code,
                    }
                )

        # Convert the list of incomplete products to JSON
        json_response = json.dumps(incomplete_products)
        logger.info(f"Found {len(incomplete_products)} products with missing fields.")

        # Output the JSON response
        self.stdout.write(self.style.SUCCESS(json_response))
