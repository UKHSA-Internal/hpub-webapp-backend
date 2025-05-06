import logging
from functools import wraps

logger = logging.getLogger(__name__)

# Map your signal‐handler names to the statuses they care about:
_STATUS_MAP = {
    "send_product_draft_event": "draft",
    "send_product_live_event": "live",
    "send_product_archived_event": "archived",
    "send_product_withdrawn_event": "withdrawn",
}


def check_required_event_fields(required_fields):
    """
    Decorator that:
      1. Finds the expected status for this handler by name.
      2. If instance.status != expected, returns immediately.
      3. For each required_field, tries instance.field then instance.update_ref.field.
      4. If any are still None → log & return False.
      5. Else → call the wrapped function.
    """

    def decorator(func):
        expected_status = _STATUS_MAP.get(func.__name__)
        if expected_status is None:
            # Not one of our mapped handlers: no wrapping needed.
            return func

        def _fetch(instance, field):
            # Try on instance first, then on update_ref
            val = getattr(instance, field, None)
            if val is None and getattr(instance, "update_ref", None):
                val = getattr(instance.update_ref, field, None)
            return val

        @wraps(func)
        def wrapper(sender, instance, **kwargs):
            # Early exit if status doesn’t match
            current = (getattr(instance, "status", "") or "").lower()
            if current != expected_status:
                return

            # Collect any missing required fields
            missing = [f for f in required_fields if _fetch(instance, f) is None]
            if missing:
                logger.error("Missing required fields: %s", ", ".join(missing))
                return False

            return func(sender, instance, **kwargs)

        return wrapper

    return decorator
