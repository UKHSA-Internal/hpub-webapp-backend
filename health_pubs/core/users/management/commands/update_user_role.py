from django.core.management.base import BaseCommand
from core.users.models import User
from core.roles.models import Role
import logging

# Setup logger
logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Update a user's role_ref from User to Admin"

    def add_arguments(self, parser):
        parser.add_argument("email", type=str, help="Email of the user to update")

    def handle(self, *args, **kwargs):
        email = kwargs["email"]

        try:
            # Get the user with role_ref pointing to the User role
            user = User.objects.get(
                email=email, role_ref__name="User"
            )  # Ensure "User" is the actual role name
            logger.info(
                f"User Found: {user.first_name} {user.last_name} - Current Role: {user.role_ref.name}"
            )

            # Get the Admin role instance
            admin_role = Role.objects.get(
                name="Admin"
            )  # Ensure "Admin" is the correct role name in your DB

            # Assign the Role instance instead of a string
            user.role_ref = admin_role
            user.save(update_fields=["role_ref"])

            self.stdout.write(
                self.style.SUCCESS(f"Successfully updated {email} to Admin.")
            )

        except User.DoesNotExist:
            self.stdout.write(
                self.style.ERROR(
                    f"User with email {email} and role_ref='User' not found."
                )
            )
        except Role.DoesNotExist:
            self.stdout.write(
                self.style.ERROR("Admin role not found in the Role table.")
            )
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"An error occurred: {e}"))
