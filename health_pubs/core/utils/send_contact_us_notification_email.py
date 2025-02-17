import os
import sys

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
import logging

import requests
import config
from notifications_python_client.notifications import NotificationsAPIClient

# Load the configuration module

logger = logging.getLogger(__name__)

def send_notification(contact_name, contact_email, summary, message):
    try:
        # GOV.UK Notify API credentials
        api_key = config.GOV_UK_NOTIFY_API_KEY

        contact_email_address = (
            config.CONTACT_US_APS_EMAIL_ADDRESS
        )
        # logging.info("contact_email_address", contact_email_address)

        # Retrieve the email template ID
        template_id = config.CONTACT_US_TEMPLATE_ID
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
