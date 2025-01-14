from core.establishments.models import Establishment
from core.organizations.models import Organization
from core.roles.models import Role
from django.contrib.auth.hashers import make_password
from django.db import models
from django.utils import timezone
from wagtail.admin.panels import FieldPanel
from wagtail.models import Page


class User(Page):
    user_id = models.CharField(
        primary_key=True,
        unique=True,
        editable=False,
        max_length=225,
    )
    email = models.EmailField(unique=True)
    email_verified = models.BooleanField(default=False)
    mobile_number = models.CharField(max_length=100, null=True, blank=True)
    password = models.CharField(max_length=255, blank=True, null=True)
    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)
    is_authorized = models.BooleanField(default=False)

    establishment_ref = models.ForeignKey(
        Establishment,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )

    organization_ref = models.ForeignKey(
        Organization,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="users",
    )

    role_ref = models.ForeignKey(
        Role, null=True, on_delete=models.SET_NULL, related_name="users"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_login = models.DateTimeField(null=True, blank=True)

    # Panels for Wagtail admin interface
    content_panels = Page.content_panels + [
        FieldPanel("email"),
        FieldPanel("email_verified"),
        FieldPanel("mobile_number"),
        FieldPanel("password"),
        FieldPanel("first_name"),
        FieldPanel("last_name"),
        FieldPanel("establishment_ref"),
        FieldPanel("organization_ref"),
        FieldPanel("role_ref"),
        FieldPanel("is_authorized"),
        FieldPanel("last_login"),
    ]

    def set_password(self, raw_password):
        """Hashes the password and stores it."""
        self.password = make_password(raw_password)

    def save(self, *args, **kwargs):
        """Overrides the save method to hash the password if necessary."""
        # Only hash the password if it's not already hashed
        if self.password and len(self.password) < 60:
            self.password = make_password(self.password)

        super().save(*args, **kwargs)

    def is_authenticated(self):
        return self.is_authorized

    def update_last_login(self):
        """Updates the last_login field to the current time in an aware format."""
        self.last_login = timezone.now()


class InvalidatedToken(Page):
    # Reference to the user
    users = models.ForeignKey(
        User, null=True, on_delete=models.SET_NULL, related_name="invalidated_tokens"
    )
    token = models.TextField(unique=True)  # Store invalidated tokens
    invalidated_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Token for {self.users.email}: {self.token}"
