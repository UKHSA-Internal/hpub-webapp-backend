from django.core.management.base import BaseCommand

from core.auth import services


class Command(BaseCommand):
    help = "Get auth token from local browser."

    def handle(self, *args, **options):
        auth_token = services.get_access_token_from_browser()
        self.stdout.write(self.style.SUCCESS(f"Access Token: {auth_token}"))
