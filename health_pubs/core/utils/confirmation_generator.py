import secrets
import string
from core.orders.models import Order


def generate_confirmation_number(prefix: str = "FHR", length: int = 5) -> str:
    """
    Generate a unique confirmation number with the given prefix and random suffix.

    Args:
        prefix (str): The prefix for the confirmation number. Defaults to "FHR".
        length (int): The length of the random suffix. Defaults to 5.

    Returns:
        str: A unique confirmation number.
    """
    # Define allowed characters for the random suffix
    allowed_chars = string.ascii_uppercase + string.digits

    # Generate initial confirmation number
    random_suffix = "".join(secrets.choice(allowed_chars) for _ in range(length))
    confirmation_number = prefix + random_suffix

    # Ensure the confirmation number is unique by querying existing orders
    while Order.objects.filter(order_confirmation_number=confirmation_number).exists():
        random_suffix = "".join(secrets.choice(allowed_chars) for _ in range(length))
        confirmation_number = prefix + random_suffix

    return confirmation_number
