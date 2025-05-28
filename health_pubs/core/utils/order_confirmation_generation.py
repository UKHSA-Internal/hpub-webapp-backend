from .confirmation_generator import generate_confirmation_number
from core.orders.models import OrderItem


def title_case(s):
    if not s or s == "-":
        return "-"
    return s.title()


def generate_order_confirmation(order_instance):
    """
    Generate a unique order confirmation number and format the order details.
    Args:
        order_instance (Order): The order instance for which to generate the confirmation.
    Returns:
        dict: A dictionary containing the formatted order details.
    """
    # Generate unique confirmation number
    confirmation_number = generate_confirmation_number()

    items = OrderItem.objects.filter(order_ref=order_instance)

    # Build the ordered products list in a table-like format
    items_table = "\n".join(
        f"{idx}. {item.product_ref.title}(Quantity - {item.quantity})"
        for idx, item in enumerate(items, start=1)
    )
    total_items = sum(
        item.quantity for item in OrderItem.objects.filter(order_ref=order_instance)
    )
    # items_table += f"\nTotal Items: {total_items}"

    # Retrieve shipping address and user details
    user = order_instance.user_ref
    address = order_instance.address_ref
    order_date = order_instance.created_at.strftime("%Y-%m-%d %H:%M:%S")
    shipping_address = {
        "name": f"{user.first_name} {user.last_name}",
        "address_line_1": title_case(address.address_line1) or "-",
        "address_line_2": title_case(address.address_line2) or "-",
        "address_line_3": title_case(address.address_line3) or "-",
        "city": title_case(address.city) or "-",
        "postcode": address.postcode or "-",
        "country": "Uk",
        "telephone": user.mobile_number or "-",
    }

    # Construct and return the result as a dictionary matching the email template format
    result = {
        "confirmation_number": confirmation_number,
        "order_id": str(order_instance.order_id),
        "order_date": order_date,
        "items_table": items_table,
        "total_items": total_items,
        "shipping_address": shipping_address,
    }

    return result
