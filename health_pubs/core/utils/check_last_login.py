import logging
from datetime import timedelta

from core.users.models import User
from django.utils import timezone

# Setup logger
logger = logging.getLogger(__name__)


def lambda_handler(event, context):
    # Define the threshold for inactivity - which is 3 years
    threshold_date = timezone.now() - timedelta(days=3 * 365)

    # Fetch users who haven't logged in since the threshold date
    inactive_users = User.objects.filter(last_login__lt=threshold_date)

    # Process inactive users
    for user in inactive_users:
        #  deactivate user (set is_authorized to False)
        user.is_authorized = False
        user.save()

        # We can log the deactivation or send notifications
        logging.info(f"Deactivated user: {user.email}")

    return {"statusCode": 200, "body": f"{inactive_users.count()} users processed."}
