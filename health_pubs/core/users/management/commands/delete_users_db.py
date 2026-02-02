import logging
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

from core.users.models import User

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

            # Hard delete the user page tree (Wagtail Page subclass).
            user_instance.delete(hard=True)
            logger.info("User with user_id %s hard deleted successfully.", user_id)
            return {"success": True}

    except ObjectDoesNotExist:
        logger.error("User with user_id %s does not exist.", user_id)
        return {"error": "User not found"}
    except Exception as e:
        logger.error("Error deleting user with user_id %s: %s", user_id, str(e))
        return {"error": str(e)}
