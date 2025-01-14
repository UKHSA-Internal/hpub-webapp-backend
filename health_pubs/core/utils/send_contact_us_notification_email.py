import os
import sys

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
import logging

import requests
from configs.get_secret_config import Config
from notifications_python_client.notifications import NotificationsAPIClient

# Load the configuration module

logger = logging.getLogger(__name__)

gov_notify_config = Config()


def send_notification(contact_name, contact_email, summary, message):
    try:
        # GOV.UK Notify API credentials
        api_key = gov_notify_config.get_gov_uk_notify_api_key()

        contact_email_address = (
            gov_notify_config.get_gov_uk_notify_contact_us_email_address()
        )
        # logging.info("contact_email_address", contact_email_address)

        # Retrieve the email template ID
        template_id = gov_notify_config.get_gov_uk_notify_contact_us_email_template_id()
        # logging.info("TEMPLATE_ID", template_id)

        # Check if required values are available
        if not api_key or not template_id:
            raise ValueError(
                "Missing one or more configuration values: 'GOV_UK_NOTIFY_API_KEY', 'GOV_UK_NOTIFY_EMAIL_TEMPLATE_ID'."
            )

        # Create an instance of the NotificationsAPIClient
        notifications_client = NotificationsAPIClient(api_key)

        # Prepare the data payload for the notification
        data = {
            "personalisation": {
                "contact_name": contact_name,
                "contact_email": contact_email,
                "summary": summary,
                "message": message,
            },
        }

        # Send the email notification
        response = notifications_client.send_email_notification(
            email_address=contact_email_address,
            template_id=template_id,
            personalisation=data["personalisation"],
        )
        # logger.info(f"EMAIL sent successfully to {contact_email_address}")

        return f"Successfully sent confirmation number: {response}", 200

    except requests.exceptions.HTTPError as http_err:
        logger.error(f"HTTP error occurred while sending email: {http_err}")
        return f"Failed to send email: {http_err}", (
            http_err.response.status_code if hasattr(http_err, "response") else 500
        )
    except ValueError as val_err:
        logger.error(f"Configuration error: {val_err}")
        return f"Configuration error: {val_err}", 400
    except Exception as e:
        logger.exception(f"Unexpected error occurred while sending email: {e}")
        return f"Unexpected error occurred: {e}", 500
