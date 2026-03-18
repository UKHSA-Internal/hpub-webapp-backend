from django.core.management.base import BaseCommand
from ...models import Address  # adjust import to your actual model
from core.utils.address_normalizer import normalize_address_instance


class Command(BaseCommand):
    help = "Normalize all addresses in DB to enforce character limits with spillover."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would change but do not update the DB.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        updated = 0
        total = Address.objects.count()

        for addr in Address.objects.iterator():
            normalized = normalize_address_instance(addr)

            new_line1, new_line2, new_line3 = normalized["address_lines"]
            new_city = normalized["city"]
            new_county = normalized["county"]
            new_postcode = normalized["postcode"]
            new_country = normalized["country"]

            if (
                addr.address_line1 != new_line1
                or addr.address_line2 != new_line2
                or addr.address_line3 != new_line3
                or addr.city != new_city
                or addr.county != new_county
                or addr.postcode != new_postcode
                or addr.country != new_country
            ):
                updated += 1

                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"[DRY RUN] Address {addr.id} would change:\n"
                            f"  line1: {addr.address_line1!r} -> {new_line1!r}\n"
                            f"  line2: {addr.address_line2!r} -> {new_line2!r}\n"
                            f"  line3: {addr.address_line3!r} -> {new_line3!r}\n"
                            f"  city: {addr.city!r} -> {new_city!r}\n"
                            f"  county: {addr.county!r} -> {new_county!r}\n"
                            f"  postcode: {addr.postcode!r} -> {new_postcode!r}\n"
                            f"  country: {addr.country!r} -> {new_country!r}\n"
                        )
                    )
                else:
                    addr.address_line1 = new_line1
                    addr.address_line2 = new_line2
                    addr.address_line3 = new_line3
                    addr.city = new_city
                    addr.county = new_county
                    addr.postcode = new_postcode
                    addr.country = new_country
                    addr.save(
                        update_fields=[
                            "address_line1",
                            "address_line2",
                            "address_line3",
                            "city",
                            "county",
                            "postcode",
                            "country",
                            "modified_at",
                        ]
                    )

        mode = "DRY RUN" if dry_run else "UPDATED"
        self.stdout.write(
            self.style.SUCCESS(
                f"{mode}: {updated} / {total} addresses would be normalized."
            )
        )
