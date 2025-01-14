import logging
from functools import wraps

logger = logging.getLogger(__name__)


def check_required_event_fields(required_fields):
    def decorator(func):
        @wraps(func)
        def wrapper(sender, instance, **kwargs):
            # Check if all required fields are strings
            if not all(isinstance(field, str) for field in required_fields):
                logger.error("All required fields must be strings.")
                return False  # Or raise an exception

            # Initialize data dictionary
            data = {field: getattr(instance, field, None) for field in required_fields}

            # Include fields from the update_ref if it exists
            if instance.update_ref is not None:  # Check if update_ref is not None
                update_ref = instance.update_ref
                data.update(
                    {
                        "minimum_stock_level": update_ref.minimum_stock_level,
                        "run_to_zero": update_ref.run_to_zero,
                        "cost_centre": update_ref.cost_centre,
                        "unit_of_measure": update_ref.unit_of_measure,
                        "local_code": update_ref.local_code,
                        "stock_owner_email_address": update_ref.stock_owner_email_address,
                        "order_referral_email_address": update_ref.order_referral_email_address,
                    }
                )

            # Check for missing required fields
            missing_fields = [
                field for field in required_fields if data.get(field) is None
            ]
            if missing_fields:
                logger.error(f"Missing required fields: {', '.join(missing_fields)}")
                return False  # Return False if fields are missing

            # Proceed if all required fields are present
            return func(sender, instance, **kwargs)

        return wrapper

    return decorator
