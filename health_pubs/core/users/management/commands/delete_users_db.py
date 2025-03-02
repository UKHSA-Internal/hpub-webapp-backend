import sys
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

from core.users.models import User
from wagtail.models import Page  # Explicitly import Page from wagtail.models

logger = logging.getLogger(__name__)


def delete_user_and_dependencies(user_id: str) -> dict:
    """
    Hard deletes a user and all of its associated Wagtail pages and dependencies.

    This function:
      - Retrieves the User record by user_id.
      - If the user has an associated Wagtail page (assumed to be stored in a 'page' attribute),
        it explicitly queries the Page model to retrieve that page, and then calls its hard delete method.
      - Finally, it deletes the User record.

    Note: Ensure cascading delete settings are configured so that all related data (e.g., revisions,
    workflow data, etc.) is removed.
    """
    try:
        with transaction.atomic():
            user_instance = User.objects.get(user_id=user_id)

            # Explicitly retrieve the associated Page using the Page model.
            if hasattr(user_instance, "page") and user_instance.page:
                page_id = user_instance.page.id
                page = Page.objects.get(id=page_id)
                # Hard delete the page tree.
                page.delete(hard=True)
                logger.info(
                    "Hard deleted Wagtail page tree (Page id: %s) for user_id %s.",
                    page_id,
                    user_id,
                )

            # Delete the User record.
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
    help = (
        "Hard delete a user along with all associated Wagtail pages and dependencies."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "user_id", type=str, help="The unique user_id of the user to delete."
        )

    def handle(self, *args, **options):
        user_id = options["user_id"]
        result = delete_user_and_dependencies(user_id)

        if result.get("success"):
            self.stdout.write(
                self.style.SUCCESS(
                    f"User {user_id} and all related Wagtail dependencies were hard deleted successfully."
                )
            )
        else:
            error_message = result.get("error", "Unknown error")
            self.stdout.write(
                self.style.ERROR(f"Error deleting user {user_id}: {error_message}")
            )
            sys.exit(1)
