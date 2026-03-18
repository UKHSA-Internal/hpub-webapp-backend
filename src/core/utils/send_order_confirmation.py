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
    first_name,  # greeting name (now: delivery user's first name)
    sender_full_name,  # fallback for delivery name if shipping dict is missing
    confirmation_number,
    order_date,
    items_table,
    total_items,
    shipping_address,  # MUST be a dict with the keys below
):
    try:
        api_key = gov_notify_config.get_gov_uk_notify_api_key()
        if notification_type == "email":
            template_id = gov_notify_config.get_gov_uk_notify_email_template_id()
        elif notification_type == "sms":
            template_id = gov_notify_config.get_gov_uk_notify_sms_template_id()
        else:
            raise ValueError("Unsupported notification type.")

        if not api_key or not template_id:
            raise ValueError(
                "Missing one or more configuration values: GOV_UK_NOTIFY_API_KEY / TEMPLATE_ID."
            )

        notifications_client = NotificationsAPIClient(api_key)

        # Normalise/format date
        if isinstance(order_date, str):
            try:
                dt = datetime.fromisoformat(order_date)
            except ValueError:
                dt = datetime.strptime(order_date, "%Y-%m-%d")
        elif isinstance(order_date, date):
            dt = datetime.combine(order_date, datetime.min.time())
        else:
            dt = order_date
        formatted_order_date = dt.strftime("%d %B %Y")

        logger.info("shipping_address %s", shipping_address)

        # Build a delivery name from shipping_address first; fall back to provided sender_full_name
        delivery_name = (
            (shipping_address or {}).get("name")
            or f"{(shipping_address or {}).get('first_name','').strip()} {(shipping_address or {}).get('last_name','').strip()}".strip()
            or (sender_full_name or "").strip()
        )

        # Prepare the data payload for the notification
        # NOTE: We index with .get to avoid KeyError, then default to empty strings.
        sa = shipping_address or {}
        personalisation = {
            "first_name": first_name,  # greeting – delivery user's first name
            "confirmation_number": confirmation_number,
            "order_date": formatted_order_date,
            "items_table": items_table,
            "total_items": total_items,
            "name": delivery_name,  # full delivery name shown in address block
            "address_line_1": sa.get("address_line_1", ""),
            "address_line_2": sa.get("address_line_2", ""),
            "city": sa.get("city", ""),
            "postcode": sa.get("postcode", ""),
            "country": sa.get("country", ""),
            "telephone": sa.get("telephone", ""),
        }

        if notification_type == "email":
            response = notifications_client.send_email_notification(
                email_address=recipient,
                template_id=template_id,
                personalisation=personalisation,
            )
            logger.info("EMAIL sent successfully to %s", recipient)
        else:
            response = notifications_client.send_sms_notification(
                phone_number=recipient,
                template_id=template_id,
                personalisation=personalisation,
            )
            logger.info("SMS sent successfully to %s", recipient)

        return f"Successfully sent confirmation number: {response}", 200

    except requests.exceptions.HTTPError as http_err:
        logger.error(
            "HTTP error occurred while sending %s: %s", notification_type, http_err
        )
        return f"Failed to send {notification_type}: {http_err}", (
            http_err.response.status_code if hasattr(http_err, "response") else 500
        )
    except ValueError as val_err:
        logger.error("Configuration error: %s", val_err)
        return f"Configuration error: {val_err}", 400
    except Exception as e:
        logger.exception(
            "Unexpected error occurred while sending %s: %s", notification_type, e
        )
        return f"Unexpected error occurred: {e}", 500
