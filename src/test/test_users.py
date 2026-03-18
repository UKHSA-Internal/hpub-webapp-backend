import logging
import os
import sys
import uuid
from datetime import datetime, timedelta
from unittest.mock import patch

import jwt
import pytest
from core.establishments.models import Establishment
from core.organizations.models import Organization
from core.roles.models import Role
from core.users.models import User
from core.users.views import TokenRefresh
from core.utils.token_generation_validation import generate_long_term_token
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.timezone import now
from rest_framework import status
from rest_framework.test import APIClient
from wagtail.models import Page

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))


logger = logging.getLogger(__name__)


def generate_unique_slug(base_slug, model):
    """Generate a unique slug for the Address."""
    queryset = model.objects.filter(slug__startswith=base_slug)
    if not queryset.exists():
        return base_slug

    num = queryset.count() + 1
    return f"{base_slug}-{num}"


def get_or_create_parent_page(title, slug):
    try:
        parent_page = Page.objects.get(slug=slug)
        logger.info(f"Parent page '{title}' found with slug '{slug}'.")
    except Page.DoesNotExist:
        logger.warning(f"Parent page '{title}' not found, creating new one.")
        try:
            root_page = Page.objects.first()  # Assuming the root page is the first one
            parent_page = Page(
                title=title,
                slug=slug,
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            parent_page.save_revision().publish()  # Ensure it's published
            logger.info(f"Parent page '{title}' created with slug '{slug}'.")
        except Exception as ex:
            logger.error(f"Failed to create parent page '{title}': {str(ex)}")
            raise
    return parent_page


@pytest.fixture
def organization(db):
    """Fixture to create a sample organization."""
    slug_org = generate_unique_slug(
        f"test-organizations-{str(uuid.uuid4())}-{str(timezone.now())}", Organization
    )

    unique_root_slug = f"root-{str(uuid.uuid4())}"
    content_type = ContentType.objects.get_for_model(Page)
    root_page = Page(title="Root", slug=unique_root_slug, content_type=content_type)
    Page.objects.get(id=1).add_child(instance=root_page)
    root_page.save()

    # Create or get parent page for organizations
    organizations_page = get_or_create_parent_page("Organizations", "organizations")

    # Create or get Organization
    if not Organization.objects.filter(organization_id="1").exists():
        organization = Organization(
            title="Test Organization",
            slug=slugify(slug_org),
            organization_id="1",
            name="Test Organization",
            external_key="1234",
        )
        organizations_page.add_child(instance=organization)
        organization.save()
    else:
        organization = Organization.objects.get(organization_id="1")

    return organization


@pytest.fixture
def role(db):
    """Fixture to create a sample role."""
    slug_role = generate_unique_slug(
        f"test-role-{str(uuid.uuid4())}-{str(timezone.now())}", Role
    )

    # Create or get parent page for roles
    roles_page = get_or_create_parent_page("Roles", "roles")

    # Create or get Role
    if not Role.objects.filter(role_id="50").exists():
        role_instance = Role(
            title="Role Title", slug=slugify(slug_role), role_id="50", name="User"
        )
        roles_page.add_child(instance=role_instance)
        role_instance.save()
    else:
        role_instance = Role.objects.get(role_id="50")

    return role_instance


@pytest.fixture
def user(db, establishment_data, role):
    """Fixture to create a sample user."""
    slug_user = generate_unique_slug(
        f"test-user-{str(uuid.uuid4())}-{str(timezone.now())}", User
    )

    # Create or get parent page for establishments
    users_page = get_or_create_parent_page("Users", "users")

    # Create or get User
    if not User.objects.filter(email="testuser@example.com").exists():
        user_instance = User(
            title="User Title",
            slug=slugify(slug_user),
            user_id="dddb654c-58f8-4aa6-80f3-06b100546546",
            email="testuser@example.com",
            email_verified=True,
            mobile_number="1234567890",
            first_name="Test",
            last_name="User",
            is_authorized=True,
            establishment_ref=establishment_data,
            organization_ref=establishment_data.organization_ref,
            role_ref=role,
        )
        user_instance.set_password("password123")
        users_page.add_child(instance=user_instance)
        user_instance.save()
    else:
        user_instance = User.objects.get(email="testuser@example.com")

    return user_instance


@pytest.fixture
def role_admin(db):
    """Fixture to create a sample role."""
    slug_role = generate_unique_slug(
        f"test-role-{str(uuid.uuid4())}-{str(timezone.now())}", Role
    )

    # Create or get parent page for roles
    roles_page = get_or_create_parent_page("Roles", "roles")

    # Create or get Role
    if not Role.objects.filter(role_id="51").exists():
        role_instance = Role(
            title="Role Admin Title",
            slug=slugify(slug_role),
            role_id="51",
            name="Admin",
        )
        roles_page.add_child(instance=role_instance)
        role_instance.save()
    else:
        role_instance = Role.objects.get(role_id="51")

    return role_instance


@pytest.fixture
def user_admin(db, establishment_data, role_admin):
    """Fixture to create a sample user."""
    slug_user = generate_unique_slug(
        f"test-user-{str(uuid.uuid4())}-{str(timezone.now())}", User
    )

    # Create or get parent page for establishments
    users_page = get_or_create_parent_page("Users", "users")

    # Create or get User
    if not User.objects.filter(email="testuser2@example.com").exists():
        user_instance = User(
            title="User Admin Title",
            slug=slugify(slug_user),
            user_id="dddb654c-58f8-4aa6-80f3-06b10054696y",
            email="testuser2@example.com",
            email_verified=True,
            mobile_number="1234567890",
            first_name="Test2",
            last_name="User2",
            is_authorized=True,
            establishment_ref=establishment_data,
            organization_ref=establishment_data.organization_ref,
            role_ref=role_admin,
        )
        user_instance.set_password("password123")
        users_page.add_child(instance=user_instance)
        user_instance.save()
    else:
        user_instance = User.objects.get(email="testuser2@example.com")

    return user_instance


@pytest.fixture
def establishment_data(db, organization):
    """Fixture to create a sample establishment."""
    slug_establishment = generate_unique_slug(
        f"test-establishment-{str(uuid.uuid4())}-{str(timezone.now())}", Establishment
    )

    # Create or get parent page for establishments
    establishments_page = get_or_create_parent_page("Establishments", "establishments")

    # Create or get Establishment
    if not Establishment.objects.filter(establishment_id="130").exists():
        establishment = Establishment(
            establishment_id="130",
            title="Test Establishment",
            slug=slugify(slug_establishment),
            organization_ref=organization,
            name="Test Establishment",
            full_external_key="TE|TP",
        )
        establishments_page.add_child(instance=establishment)
        establishment.save()
    else:
        establishment = Establishment.objects.get(establishment_id="130")

    return establishment


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_api_client_user(api_client, user):
    token_payload = {
        "user_id": str(user.user_id),
        "email": user.email,
        "type": "access",
    }
    from django.conf import settings

    token = jwt.encode(token_payload, settings.PRIVATE_KEY, algorithm="RS256")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


@pytest.fixture
def auth_api_client_user_azure(api_client, user_admin):
    """Fixture to authenticate an API client with a mock Azure B2C token."""

    def generate_mock_azure_b2c_token(email):
        """Generate a mock Azure B2C token for testing purposes."""
        from configs.get_secret_config import Config

        config = Config()
        client_id = config.get_azure_b2c_client_id()
        policy_name = config.get_azure_b2c_policy_name()
        issuer = config.get_azure_b2c_issuer()

        payload = {
            "emails": [email],
            "given_name": user_admin.first_name,
            "family_name": user_admin.last_name,
            "iss": issuer,
            "tfp": policy_name,
            "aud": client_id,
            "exp": (datetime.now() + timedelta(minutes=30)).timestamp(),
            "iat": datetime.now().timestamp(),
        }

        from django.conf import settings

        private_key = settings.PRIVATE_KEY
        return jwt.encode(payload, private_key, algorithm="RS256")

    # Generate a mock Azure B2C token for the user
    token = generate_mock_azure_b2c_token(user_admin.email)

    # Set the token as the Authorization header
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


@pytest.fixture
def auth_api_client_user_azure_non_existent(
    api_client,
):
    """Fixture to authenticate an API client with a mock Azure B2C token."""

    def generate_mock_azure_b2c_token(email):
        """Generate a mock Azure B2C token for testing purposes."""
        from configs.get_secret_config import Config

        config = Config()
        client_id = config.get_azure_b2c_client_id()
        policy_name = config.get_azure_b2c_policy_name()
        issuer = config.get_azure_b2c_issuer()

        payload = {
            "emails": ["nonexistent@example.com"],
            "given_name": "Non",
            "family_name": "Existent",
            "iss": issuer,
            "tfp": policy_name,
            "aud": client_id,
            "exp": (datetime.now() + timedelta(minutes=30)).timestamp(),
            "iat": datetime.now().timestamp(),
        }

        from django.conf import settings

        private_key = settings.PRIVATE_KEY
        return jwt.encode(payload, private_key, algorithm="RS256")

    # Generate a mock Azure B2C token for the user
    token = generate_mock_azure_b2c_token("nonexistent@example.com")

    # Set the token as the Authorization header
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


@pytest.fixture
def auth_api_client_user_refresh(api_client, user):
    token_payload = {
        "user_id": str(user.user_id),
        "email": user.email,
        "type": "refresh",
    }
    from django.conf import settings

    token = jwt.encode(token_payload, settings.PRIVATE_KEY, algorithm="RS256")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client, token


@pytest.fixture
def auth_api_client_user_invalid(api_client, user):

    token = "Invalid Token"
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client, token


@pytest.fixture
def auth_api_client_user_refresh_expired(api_client, expired_long_term_token):
    """Fixture to provide an API client with an expired refresh token."""
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {expired_long_term_token}")
    return api_client, expired_long_term_token


@pytest.fixture
def auth_api_client_admin(api_client, user_admin):
    token_payload = {
        "user_id": str(user_admin.user_id),
        "email": user_admin.email,
        "type": "access",
    }
    from django.conf import settings

    token = jwt.encode(token_payload, settings.PRIVATE_KEY, algorithm="RS256")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


@pytest.fixture
def auth_api_client_admin(api_client, user_admin):
    token_payload = {
        "user_id": str(user_admin.user_id),
        "email": user_admin.email,
        "type": "access",
    }
    from django.conf import settings

    token = jwt.encode(token_payload, settings.PRIVATE_KEY, algorithm="RS256")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


# Fixtures
@pytest.fixture
def token_refresh_view():
    """Fixture to provide the TokenRefresh view."""
    return TokenRefresh.as_view()


@pytest.fixture
def long_term_token(user):
    """Fixture to generate a valid long-term token for the user."""
    return generate_long_term_token(
        user_id=str(user.user_id), email=user.email, role_name="User"
    )


@pytest.fixture
def expired_long_term_token(user):
    """Fixture to generate an expired long-term token for the user."""
    with patch(
        "core.utils.token_generation_validation.timezone.now",
        return_value=now() - timedelta(days=8),
    ):
        return generate_long_term_token(
            user_id=str(user.user_id), email=user.email, role_name="User"
        )


AZURE_TOKEN = """REDACTED"""


@pytest.mark.django_db
@patch("core.users.views.validate_token_refresh")
@patch("core.users.views.generate_short_term_token")
def test_token_refresh_success(
    mock_generate_short_term_token,
    mock_validate_token_refresh,
    auth_api_client_user_refresh,
    token_refresh_view,
):
    """Test a successful token refresh."""
    mock_validate_token_refresh.return_value = {
        "user_id": "dddb654c-58f8-4aa6-80f3-06b100546546",
        "email": "testuser@example.com",
        "role": "User",
    }
    mock_generate_short_term_token.return_value = "short_term_token"

    # Unpack the API client and token from the fixture
    api_client, refresh_token = auth_api_client_user_refresh

    url = reverse("token_refresh")
    response = api_client.post(
        url, HTTP_AUTHORIZATION=f"Bearer {refresh_token}", format="json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.data == {"short_term_token": "short_term_token"}
    mock_validate_token_refresh.assert_called_once_with(
        refresh_token, token_type="refresh"
    )


@pytest.mark.django_db
@patch("core.users.views.validate_token_refresh")
def test_token_refresh_expired_token(
    mock_validate_token_refresh,
    auth_api_client_user_refresh_expired,
    token_refresh_view,
):
    """Test refresh with an expired token."""
    # Mock token refresh to raise expiration error
    mock_validate_token_refresh.side_effect = ValueError("Token expired")

    # Unpack the API client and expired token from the fixture
    api_client, _ = auth_api_client_user_refresh_expired

    url = reverse("token_refresh")
    response = api_client.post(
        url, format="json"
    )  # Authorization is already set in fixture
    print("RESPONSE", response.json())

    # Assert the response
    assert response.status_code == 403
    assert response.data == {"detail": "Token expired"}


@pytest.mark.django_db
@patch("core.users.views.validate_token_refresh")
def test_token_refresh_invalid_token(
    mock_validate_token_refresh, auth_api_client_user_invalid
):
    """Test refresh with an invalid token."""
    mock_validate_token_refresh.side_effect = ValueError("Invalid token")

    api_client, invalid_token = auth_api_client_user_invalid

    url = reverse("token_refresh")
    response = api_client.post(
        url, HTTP_AUTHORIZATION=f"Bearer {invalid_token}", format="json"
    )
    print("Request Headers:", api_client._credentials)
    print("RESPONSE", response.json())

    assert response.status_code == 403
    assert response.json() == {"detail": "Invalid token"}


@pytest.mark.django_db
def test_token_refresh_missing_authorization(api_client):
    """Test refresh without an Authorization header."""
    url = reverse("token_refresh")
    # api_client, _ = auth_api_client_user_refresh

    response = api_client.post(url, format="json")
    print("RESPONSE", response.json())

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Authentication credentials were not provided."
    }


@pytest.mark.django_db
class TestAPIs:
    @patch("core.users.views.validate_azure_b2c_token")
    def test_user_signup_positive(
        self,
        mock_validate_token,
        auth_api_client_user_azure,
        establishment_data,
        role_admin,
        user_admin,
    ):
        """Test successful user signup."""

        # Delete the pre-existing user to simulate a fresh signup
        user_admin.delete()

        # Mock the validate_azure_b2c_token to return expected claims
        mock_validate_token.return_value = {
            "given_name": "Test",
            "family_name": "User",
            "emails": ["test.user@testemail.com"],
            "extension_UserAppRole": "Admin",
        }

        # Setup request data
        url = reverse("signup")
        payload = {"establishment_id": establishment_data.establishment_id}

        # Send POST request
        response = auth_api_client_user_azure.post(url, data=payload, format="json")

        print("RES", response.json())  # Debugging output

        # Assertions
        assert response.status_code == 201
        response_data = response.json()
        assert "short_term_token" in response_data
        assert "long_term_token" in response_data

        # Validate response user data
        user_data = response_data.get("user")
        assert user_data is not None
        assert user_data["email"] == "test.user@testemail.com"
        assert user_data["first_name"] == "Test"
        assert user_data["last_name"] == "User"
        assert user_data["role_ref"]["name"] == role_admin.name

    def test_user_signup_missing_auth(self, api_client):
        """Test user signup with missing Authorization header."""
        url = reverse("signup")
        response = api_client.post(url, format="json")
        print("RES", response.json())  # Debugging response

        assert response.status_code == 401
        assert response.data["error"] == "Authorization token missing"

    @patch("core.users.views.validate_azure_b2c_token")
    def test_user_login_positive(self, mock_validate_token, api_client, user):
        """Test successful user login."""
        mock_validate_token.return_value = {"emails": [user.email]}
        url = reverse("login")
        auth_header = f"Bearer {AZURE_TOKEN}"
        response = api_client.post(url, HTTP_AUTHORIZATION=auth_header, format="json")
        print("RES", response.json())

        assert response.status_code == 200
        assert "short_term_token" in response.data

    @patch("core.users.views.validate_azure_b2c_token")
    def test_user_login_user_not_found(
        self, mock_validate_token, auth_api_client_user_azure
    ):
        """Test user login when the user is not found."""

        # Mock the validate_azure_b2c_token to return claims for a non-existent user
        mock_validate_token.return_value = {
            "emails": ["nonexistent@example.com"],
            "given_name": "Non",
            "family_name": "Existent",
        }

        # Setup request data
        url = reverse("login")

        # Send POST request
        response = auth_api_client_user_azure.post(url, format="json")

        print("RES", response.json())  # Debugging output

        # Assertions
        assert response.status_code == 404
        assert response.json() == {"error": "User not found"}

    def test_user_update_positive(self, auth_api_client_user, user):
        """Test updating user details."""
        url = reverse("update-user-view")
        payload = {"user_id": user.user_id, "first_name": "UpdatedName"}
        response = auth_api_client_user.put(url, data=payload, format="json")

        assert response.status_code == 200
        assert response.data["message"] == "User updated successfully"

    def test_user_update_missing_user_id(self, auth_api_client_user):
        """Test user update with missing user ID."""
        url = reverse("update-user-view")
        payload = {}
        response = auth_api_client_user.put(url, data=payload, format="json")

        assert response.status_code == 400
        assert response.data["error"] == "User ID is required"

    def test_logout_positive(self, auth_api_client_user):
        """Test successful user logout."""
        url = reverse("logout")
        response = auth_api_client_user.post(url, format="json")

        assert response.status_code == 200
        assert response.data["message"] == "Successfully logged out"

    def test_logout_missing_token(self, api_client):
        """Test logout without Authorization token."""
        url = reverse("logout")
        response = api_client.post(url, format="json")
        print("RES", response.json())  # Debugging response
        assert response.status_code == 403
        assert (
            response.data["detail"] == "Authentication credentials were not provided."
        )

    def test_user_detail_positive(self, auth_api_client_user, user):
        """Test retrieving user details."""
        url = reverse("user-detail", kwargs={"user_id": str(user.user_id)})
        response = auth_api_client_user.get(url, format="json")

        assert response.status_code == 200
        assert response.data["email"] == user.email

    def test_user_detail_user_not_found(self, auth_api_client_user):
        """Test retrieving user details with invalid user ID."""
        invalid_user_id = str(uuid.uuid4())
        url = reverse("user-detail", kwargs={"user_id": invalid_user_id})
        response = auth_api_client_user.get(url, format="json")
        print("RES", response.json())

        assert response.status_code == 404
        assert response.data["detail"] == "No User matches the given query."


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """
    Teardown fixture to clean up the database after each test function.
    Ensures the database is in a clean state for the next test.
    """

    def teardown():
        # Clear all relevant models
        Establishment.objects.all().delete()
        Organization.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()

        # Log the cleanup
        logger.info("Database has been cleaned up after the test.")

    # Add the cleanup step to pytest finalizer
    request.addfinalizer(teardown)
