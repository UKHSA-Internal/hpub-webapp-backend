import sys
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

# Import your User model; adjust the import path as needed.
from core.users.models import User

logger = logging.getLogger(__name__)


def delete_user(user_id: str) -> dict:
    """
    Deletes a user and, if applicable, the associated Wagtail page tree.
    """
    try:
        with transaction.atomic():
            user_instance = User.objects.get(user_id=user_id)

            # If your User model is a subclass of Wagtail Page, this will remove its tree.
            # Otherwise, if there's an associated page relation, delete that tree.
            if hasattr(user_instance, "page"):
                # If the user has an associated page, delete that page.
                user_instance.page.delete()
            else:
                # Otherwise, delete the user instance directly.
                user_instance.delete()

            logger.info("User with user_id %s deleted successfully.", user_id)
            return {"success": True}

    except ObjectDoesNotExist:
        logger.error("User with user_id %s does not exist.", user_id)
        return {"error": "User not found"}
    except Exception as e:
        logger.error("Error deleting user with user_id %s: %s", user_id, str(e))
        return {"error": str(e)}


class Command(BaseCommand):
    help = "Delete a user by user_id along with its associated Wagtail pages."

    def add_arguments(self, parser):
        parser.add_argument(
            "user_id", type=str, help="The unique user_id of the user to delete."
        )

    def handle(self, *args, **options):
        user_id = options["user_id"]
        result = delete_user(user_id)

        if result.get("success"):
            self.stdout.write(
                self.style.SUCCESS(f"User {user_id} deleted successfully.")
            )
        else:
            error_message = result.get("error", "Unknown error")
            self.stdout.write(
                self.style.ERROR(f"Error deleting user {user_id}: {error_message}")
            )
            sys.exit(1)
