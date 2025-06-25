import logging
import os
import sys
from datetime import datetime, date
import requests
from configs.get_secret_config import Config
from notifications_python_client.notifications import NotificationsAPIClient

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

# Load the configuration module

logger = logging.getLogger(__name__)

gov_notify_config = Config()


def send_notification(
    notification_type,
    recipient,
    first_name,
    sender_full_name,
    confirmation_number,
    order_date,
    items_table,
    total_items,
    shipping_address,
):
    try:
        # GOV.UK Notify API credentials
        api_key = gov_notify_config.get_gov_uk_notify_api_key()

        # Use existing methods to get the template ID
        if notification_type == "email":
            template_id = gov_notify_config.get_gov_uk_notify_email_template_id()
        elif notification_type == "sms":
            template_id = gov_notify_config.get_gov_uk_notify_sms_template_id()
        else:
            raise ValueError("Unsupported notification type.")

        # Check if all required values are available
        if not api_key or not template_id:
            raise ValueError(
                f"Missing one or more configuration values: 'GOV_UK_NOTIFY_API_KEY', 'GOV_UK_NOTIFY_{notification_type.upper()}_TEMPLATE_ID'."
            )

        # Create an instance of the NotificationsAPIClient
        notifications_client = NotificationsAPIClient(api_key)

        # Parse order_date if it's a string
        if isinstance(order_date, str):
            try:
                # Assuming ISO 8601 format, e.g. "2025-06-14" or with time
                dt = datetime.fromisoformat(order_date)
            except ValueError:
                logger.warning(
                    "order_date string not ISO‐formatted, trying common formats",
                    exc_info=True,
                )
                # Fallback: try common date-only format
                dt = datetime.strptime(order_date, "%Y-%m-%d")
        elif isinstance(order_date, date):
            # Convert date to datetime for strftime
            dt = datetime.combine(order_date, datetime.min.time())
        else:
            # Already a datetime
            dt = order_date

        # logging.info("items_table", items_table)
        formatted_order_date = dt.strftime("%d %B %Y")

        # Prepare the data payload for the notification
        data = {
            "personalisation": {
                "first_name": first_name,
                "confirmation_number": confirmation_number,
                "order_date": formatted_order_date,
                "items_table": items_table,
                "total_items": total_items,
                "name": sender_full_name,
                "address_line_1": shipping_address["address_line_1"],
                "address_line_2": shipping_address["address_line_2"],
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
