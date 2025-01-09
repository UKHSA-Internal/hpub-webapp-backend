from core.products.models import Product
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Update product_code_no_dashes for all products"

    def handle(self, *args, **kwargs):
        # Fetch all products
        products = Product.objects.all()
        updated_count = 0

        for product in products:
            if product.product_code:
                # Remove dashes and spaces from product_code
                no_dashes = product.product_code.replace("-", "").replace(" ", "")
                if product.product_code_no_dashes != no_dashes:
                    product.product_code_no_dashes = no_dashes
                    product.save()
                    updated_count += 1

        self.stdout.write(
            self.style.SUCCESS(f"Successfully updated {updated_count} products.")
        )
