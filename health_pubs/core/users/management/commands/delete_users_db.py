import logging
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist

from core.addresses.models import Address
from core.customer_support.models import CustomerSupport
from core.event_analytics.models import EventAnalytics
from core.feedbacks.models import Feedback
from core.orders.models import Order, OrderItem
from core.users.models import InvalidatedToken, User

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

            # Delete all related data for this user
            def _delete_queryset(qs, label: str) -> None:
                items = list(qs)
                for obj in items:
                    obj.delete()
                if items:
                    logger.info(
                        "Deleted %s %s for user_id %s.",
                        len(items),
                        label,
                        user_id,
                    )

            # Addresses
            _delete_queryset(Address.objects.filter(user_ref_id=user_id), "addresses")
            # Customer support records
            _delete_queryset(
                CustomerSupport.objects.filter(user_ref_id=user_id),
                "customer_support records",
            )
            # Event analytics records
            _delete_queryset(
                EventAnalytics.objects.filter(user_ref_id=user_id),
                "event_analytics records",
            )
            # Feedback
            _delete_queryset(
                Feedback.objects.filter(user_ref_id=user_id), "feedback records"
            )

            # Orders + order items
            orders = list(Order.objects.filter(user_ref_id=user_id))
            order_ids = [o.order_id for o in orders]
            if order_ids:
                # Order items for those orders
                _delete_queryset(
                    OrderItem.objects.filter(order_ref_id__in=order_ids),
                    "order items",
                )
            # Orders
            for order in orders:
                order.delete()
            if orders:
                logger.info("Deleted %s orders for user_id %s.", len(orders), user_id)

            # Invalidated tokens
            _delete_queryset(
                InvalidatedToken.objects.filter(users_id=user_id),
                "invalidated tokens",
            )

            # Delete user account
            user_instance.delete()
            logger.info("User with user_id %s deleted successfully.", user_id)
            return {"success": True}

    except ObjectDoesNotExist:
        logger.error("User with user_id %s does not exist.", user_id)
        return {"error": "User not found"}
    except Exception as e:
        logger.error("Error deleting user with user_id %s: %s", user_id, str(e))
        return {"error": str(e)}
