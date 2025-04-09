from datetime import datetime
import random
import string
from core.orders.models import OrderItem


def generate_order_confirmation(order_instance):
    # Generating order confirmation info
    random_suffix = "".join(
        random.choice(string.ascii_uppercase + string.digits) for _ in range(5)
    )
    confirmation_number = (
        "FHR" + random_suffix
    )  # 8 characters in total: FHR prefix + 5 random alphanumerics
    order_status = "Submitted"  # Assuming the status is "Submitted" for all orders
    confirmation_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Building ordered products list in a table format
    items_table = "\n".join(
        f" - Item: {item.product_ref.title} - Quantity: {item.quantity}"
        for item in OrderItem.objects.filter(order_ref=order_instance)
    )
    # Shipping address details
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

    # Construct the response object to match the email template format
    result = {
        "confirmation_number": confirmation_number,
        "order_id": str(order_instance.order_id),
        "order_status": order_status,
        "confirmation_date": confirmation_date,
        "items_table": items_table,
        "shipping_address": shipping_address,
    }

    return result
