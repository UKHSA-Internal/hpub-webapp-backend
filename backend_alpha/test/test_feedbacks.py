import logging
import uuid

import jwt
import pytest
from core.establishments.models import Establishment
from core.feedbacks.models import Feedback
from core.organizations.models import Organization
from core.roles.models import Role
from core.users.models import User
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient
from wagtail.models import Page

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
            title="Role Title", slug=slugify(slug_role), role_id="50", name="ADMIN"
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
            user_id=str(uuid.uuid4()),
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
def organization(db):
    """Fixture to create a sample organization."""
    slug_org = generate_unique_slug(
        f"test-organizations-{str(uuid.uuid4())}-{str(timezone.now())}", Organization
    )

    unique_root_slug = f"root-{str(uuid.uuid4())}"
    content_type = ContentType.objects.get_for_model(Page)
    root_page = Page(title="Root", slug=unique_root_slug, content_type=content_type)
    Page.objects.get(id=1).add_child(instance=root_page)
    root_page.save_revision().publish()

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
        )
        establishments_page.add_child(instance=establishment)
        establishment.save()
    else:
        establishment = Establishment.objects.get(establishment_id="130")

    return establishment


@pytest.fixture
def feedback(db, user):
    slug_feedback = generate_unique_slug(
        f"test-feedback-{str(uuid.uuid4())}-{str(timezone.now())}", Feedback
    )

    content_type = ContentType.objects.get_for_model(Page)

    root_page, created = Page.objects.get_or_create(
        title="Root", slug="root", path="0001", depth=1, content_type=content_type
    )

    if created:
        root_page.save_revision().publish()

    feedbacks_page = get_or_create_parent_page("Feedback", "feedback")

    # Create or get Feedback
    if not Feedback.objects.filter(feedback_id="1").exists():
        feedback = Feedback(
            feedback_id="1",
            title="Test Feedback",
            slug=slugify(slug_feedback),
            message="This is a test feedback message.",
            user_ref=user,  # Assuming the user fixture returns a User instance
        )
        feedbacks_page.add_child(instance=feedback)
        feedback.save()
    else:
        feedback = Feedback.objects.get(feedback_id="1")

    return feedback


@pytest.fixture
def role(db):
    """Fixture to create a sample role."""
    slug_role = slugify(f"test-role-{str(uuid.uuid4())}-{str(timezone.now())}")

    # Create or get parent page for roles
    roles_page = get_or_create_parent_page("Roles", "roles")

    # Create or get Role
    if not Role.objects.filter(role_id="50").exists():
        role_instance = Role(
            title="Admin Role", slug=slug_role, role_id="50", name="User"
        )
        roles_page.add_child(instance=role_instance)
        role_instance.save()
    else:
        role_instance = Role.objects.get(role_id="50")

    return role_instance


@pytest.fixture
def user(db, role):
    """Fixture to create a sample user with admin permissions."""
    slug_user = slugify(f"test-user-{str(uuid.uuid4())}-{str(timezone.now())}")

    # Create or get parent page for users
    users_page = get_or_create_parent_page("Users", "users")

    # Create or get User
    if not User.objects.filter(user_id="12345").exists():
        user_instance = User(
            user_id="12345",
            email="testuser@example.com",
            email_verified=True,
            password="testpass",
            first_name="Test",
            last_name="User",
            is_authorized=True,
            title="Test User",
            slug=slug_user,
            role_ref=role,
        )
        users_page.add_child(instance=user_instance)
        user_instance.save()
    else:
        user_instance = User.objects.get(user_id="12345")

    return user_instance


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture
def auth_api_client(api_client, user):
    token_payload = {
        "user_id": str(user.user_id),
        "email": user.email,
        "type": "access",
    }
    from django.conf import settings

    token = jwt.encode(token_payload, settings.PRIVATE_KEY, algorithm="RS256")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


@pytest.mark.django_db
class TestFeedbackViewSet:
    # Positive test for creating feedback with an authenticated user
    def test_create_feedback_authenticated_user(self, auth_api_client, user, feedback):
        url = reverse("feedback-list")
        data = {
            "feedback_id": str(uuid.uuid4()),
            "message": "This is a feedback message.",
        }
        response = auth_api_client.post(url, data, format="json")
        logging.info("response", response.json())
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["message"] == "This is a feedback message."
        assert Feedback.objects.count() == 2

    # Positive test for creating feedback with a valid user_ref
    def test_create_feedback_with_user_ref(self, auth_api_client, feedback, user):
        url = reverse("feedback-list")
        data = {
            "feedback_id": str(uuid.uuid4()),
            "message": "This is feedback with user_ref.",
            "user_ref": user.user_id,
        }
        response = auth_api_client.post(url, data, format="json")
        logging.info("response", response.json())
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["message"] == "This is feedback with user_ref."
        assert Feedback.objects.count() == 2

    # Negative test for creating feedback without an authenticated user or user_ref
    def test_create_feedback_without_user(self, api_client):
        url = reverse("feedback-list")
        data = {
            "feedback_id": str(uuid.uuid4()),
            "message": "This feedback should fail.",
        }
        response = api_client.post(url, data, format="json")
        logging.info("response", response.json())

        assert response.status_code == 403
        assert (
            response.data["detail"] == "Authentication credentials were not provided."
        )

    # Negative test for creating feedback with an invalid user_ref
    def test_create_feedback_with_invalid_user_ref(self, auth_api_client, feedback):
        url = reverse("feedback-list")
        data = {
            "feedback_id": str(uuid.uuid4()),
            "message": "This feedback should fail due to invalid user_ref.",
            "user_ref": "invalid_user_id",  # Invalid user reference
        }
        response = auth_api_client.post(url, data, format="json")

        logging.info("response", response.json())

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "User with ID invalid_user_id does not exist" in response.json()["error"]

    # Positive test for listing feedback
    def test_list_feedback(self, auth_api_client, user, feedback):

        url = reverse("feedback-list")
        response = auth_api_client.get(url)
        logging.info("response", response.json())

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) > 0
        assert response.data[0]["message"] == "This is a test feedback message."


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        Feedback.objects.all().delete()
        Establishment.objects.all().delete()
        Organization.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)


#
