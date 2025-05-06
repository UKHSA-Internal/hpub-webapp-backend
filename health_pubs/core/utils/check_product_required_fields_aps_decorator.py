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
      1. Looks up which status this handler is for (by function name).
      2. If instance.status != that status, returns immediately.
      3. Otherwise, for each required_field:
         a) Try getattr(instance, field)
         b) If None, try getattr(instance.update_ref, field)
      4. If any are still None → log & return False.
      5. Else → call the wrapped function.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(sender, instance, **kwargs):
            # 1) Determine expected status
            expected = _STATUS_MAP.get(func.__name__)
            if expected is None:
                # not one of our mapped handlers: bail
                return

            # 2) Quick status check
            status = (getattr(instance, "status", "") or "").lower()
            if status != expected:
                return

            # 3) Gather each required field from instance or update_ref
            data = {}
            for field in required_fields:
                val = getattr(instance, field, None)
                if val is None and getattr(instance, "update_ref", None):
                    upd = instance.update_ref
                    if hasattr(upd, field):
                        val = getattr(upd, field)
                data[field] = val

            # 4) Check for missing
            missing = [f for f, v in data.items() if v is None]
            if missing:
                logger.error(f"Missing required fields: {', '.join(missing)}")
                return False

            # 5) All good → run the handler
            return func(sender, instance, **kwargs)

        return wrapper

    return decorator
