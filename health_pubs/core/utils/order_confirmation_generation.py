from datetime import datetime
import secrets
import string
from core.orders.models import OrderItem, Order


def generate_order_confirmation(order_instance):
    """
    Generate a unique order confirmation number and format the order details.
    Args:
        order_instance (Order): The order instance for which to generate the confirmation.
    Returns:
        dict: A dictionary containing the formatted order details.
    """
    # Define allowed characters for random suffix generation
    allowed_chars = string.ascii_uppercase + string.digits

    # Generate initial confirmation number
    random_suffix = "".join(secrets.choice(allowed_chars) for _ in range(5))
    confirmation_number = "FHR" + random_suffix

    # Ensure the confirmation number is unique by querying existing orders
    while Order.objects.filter(confirmation_number=confirmation_number).exists():
        random_suffix = "".join(secrets.choice(allowed_chars) for _ in range(5))
        confirmation_number = "FHR" + random_suffix

    # Order status and confirmation timestamp setup
    order_status = "Submitted"  # Assuming the status is "Submitted" for all orders
    confirmation_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Build the ordered products list in a table-like format
    items_table = "\n".join(
        f" - Item: {item.product_ref.title} - Quantity: {item.quantity}"
        for item in OrderItem.objects.filter(order_ref=order_instance)
    )

    # Retrieve shipping address and user details
    user = order_instance.user_ref
    address = order_instance.address_ref
    shipping_address = {
        "name": f"{user.first_name} {user.last_name}",
        "department": user.establishment_ref.name if user.establishment_ref else "-",
        "organisation": user.organization_ref.name if user.organization_ref else "-",
        "address_line_1": address.address_line1 or "-",
        "address_line_2": address.address_line2 or "-",
        "address_line_3": address.address_line3 or "-",
        "city": address.city or "-",
        "postcode": address.postcode or "-",
        "country": address.country or "-",
        "telephone": user.mobile_number or "-",
    }

    # Construct and return the result as a dictionary matching the email template format
    result = {
        "confirmation_number": confirmation_number,
        "order_id": str(order_instance.order_id),
        "order_status": order_status,
        "confirmation_date": confirmation_date,
        "items_table": items_table,
        "shipping_address": shipping_address,
    }

    return result
