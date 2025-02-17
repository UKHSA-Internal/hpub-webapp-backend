import logging
import os
import sys

import requests
import config
from notifications_python_client.notifications import NotificationsAPIClient

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# Load the configuration module

logger = logging.getLogger(__name__)

def send_notification(
    notification_type,
    recipient,
    first_name,
    confirmation_number,
    confirmation_date,
    order_id,
    order_status,
    items_table,
    shipping_address,
):
    try:
        # GOV.UK Notify API credentials
        api_key = config.GOV_UK_NOTIFY_API_KE

        # Use existing methods to get the template ID
        if notification_type == "email":
            template_id = config.GOV_UK_NOTIFY_EMAIL_TEMPLATE_ID
        elif notification_type == "sms":
            template_id = config.GOV_UK_NOTIFY_SMS_TEMPLATE_ID
        else:
            raise ValueError("Unsupported notification type.")

        # Check if all required values are available
        if not api_key or not template_id:
            raise ValueError(
                f"Missing one or more configuration values: 'GOV_UK_NOTIFY_API_KEY', 'GOV_UK_NOTIFY_{notification_type.upper()}_TEMPLATE_ID'."
            )

        # Create an instance of the NotificationsAPIClient
        notifications_client = NotificationsAPIClient(api_key)

        # logging.info("items_table", items_table)

        # Prepare the data payload for the notification
        data = {
            "personalisation": {
                "first_name": first_name,
                "confirmation_number": confirmation_number,
                "confirmation_date": confirmation_date,
                "order_id": order_id,
                "order_status": order_status,
                "items_table": items_table,
                "name": shipping_address["name"],
                "department": shipping_address["department"],
                "organisation": shipping_address["organisation"],
                "address_line_1": shipping_address["address_line_1"],
                "address_line_2": shipping_address["address_line_2"],
                "address_line_3": shipping_address["address_line_3"],
                "city": shipping_address["city"],
                "postcode": shipping_address["postcode"],
                "country": shipping_address["country"],
                "telephone": shipping_address["telephone"],
            },
        }

        # Send the notification based on its type
        if notification_type == "email":
            response = notifications_client.send_email_notification(
                email_address=recipient,
                template_id=template_id,
                personalisation=data["personalisation"],
            )
            logger.info(f"EMAIL sent successfully to {recipient}")
        elif notification_type == "sms":
            response = notifications_client.send_sms_notification(
                phone_number=recipient,
                template_id=template_id,
                personalisation=data["personalisation"],
            )
            logger.info(f"SMS sent successfully to {recipient}")

        return f"Successfully sent confirmation number: {response}", 200

    except requests.exceptions.HTTPError as http_err:
        logger.error(
            f"HTTP error occurred while sending {notification_type}: {http_err}"
        )
        return f"Failed to send {notification_type}: {http_err}", (
            http_err.response.status_code if hasattr(http_err, "response") else 500
        )
    except ValueError as val_err:
        logger.error(f"Configuration error: {val_err}")
        return f"Configuration error: {val_err}", 400
    except Exception as e:
        logger.exception(
            f"Unexpected error occurred while sending {notification_type}: {e}"
        )
        return f"Unexpected error occurred: {e}", 500
