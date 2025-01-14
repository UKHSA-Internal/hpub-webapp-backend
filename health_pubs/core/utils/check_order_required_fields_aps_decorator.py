import logging
from functools import wraps

from django.http import JsonResponse

logger = logging.getLogger(__name__)

# Required fields for the order
required_fields = [
    "order_id",
    "user_ref",
    "address_ref",
    "full_external_key",
    "order_items",
]

# Nested required fields for user_info and order_items
user_info_required_fields = ["first_name", "last_name", "email"]
order_item_required_fields = ["product_ref", "quantity"]


def check_required_order_fields(required_fields):
    def decorator(func):
        @wraps(func)
        def wrapper(order_instance, *args, **kwargs):
            # Initialize data dictionary from order instance
            data = {
                field: getattr(order_instance, field, None) for field in required_fields
            }
            logger.info(f"Data instance: {data}")

            # Check for missing main required fields
            missing_fields = [
                field for field in required_fields if data.get(field) is None
            ]

            # Validate nested fields in user_ref (User instance)
            user_ref = data.get("user_ref")
            if user_ref:
                user_info_missing = [
                    field
                    for field in user_info_required_fields
                    if not getattr(user_ref, field, None)
                ]
                if user_info_missing:
                    missing_fields.extend(
                        [f"user_info.{field}" for field in user_info_missing]
                    )
            else:
                missing_fields.append("user_info")

            # Validate nested fields in order_items (related manager for OrderItem)
            order_items = data.get("order_items")
            if order_items:
                if not hasattr(order_items, "all"):
                    logger.error("order_items is not a valid related manager")
                    missing_fields.append("order_items")
                else:
                    for i, item in enumerate(order_items.all()):
                        item_missing = [
                            field
                            for field in order_item_required_fields
                            if not getattr(item, field, None)
                        ]
                        if item_missing:
                            missing_fields.extend(
                                [f"order_items[{i}].{field}" for field in item_missing]
                            )
            else:
                missing_fields.append("order_items")

            # If there are any missing fields, log an error and return a response
            if missing_fields:
                logger.error(f"Missing required fields: {', '.join(missing_fields)}")
                return JsonResponse(
                    {"error": f"Missing required fields: {', '.join(missing_fields)}"},
                    status=400,
                )

            # Proceed if all required fields are present
            return func(order_instance, *args, **kwargs)

        return wrapper

    return decorator
