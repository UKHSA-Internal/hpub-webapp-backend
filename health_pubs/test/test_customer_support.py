import logging
import uuid

import jwt
import pytest
from core.customer_support.models import CustomerSupport
from core.establishments.models import Establishment
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


# Utility function to create unique slugs
def generate_unique_slug(base_slug, model):
    """Generate a unique slug for the given model."""
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
            user_id="23",
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


# Fixture to create a single CustomerSupport entry
@pytest.fixture
def customer_support(db):
    """Fixture to create a sample CustomerSupport entry."""
    unique_slug = generate_unique_slug(
        f"test-customersupport-{str(uuid.uuid4())}", CustomerSupport
    )

    customer_support_id = str(uuid.uuid4())  # Generate a unique ID for testing

    # Check if the CustomerSupport entry already exists
    if not CustomerSupport.objects.filter(
        customer_support_id=customer_support_id
    ).exists():
        root_page = Page.objects.first()  # Assuming the root page is the first one
        customer_support_entry = CustomerSupport(
            customer_support_id=customer_support_id,
            title="Sample Customer Support",
            slug=slugify(unique_slug),
            user_ref=None,  # Assuming no user reference for this test
            message="This is a sample message.",
            summary="General Inquiry",
            contact_email="test@example.com",
            content_type=ContentType.objects.get_for_model(CustomerSupport),
        )
        root_page.add_child(instance=customer_support_entry)
        customer_support_entry.save()
    else:
        customer_support_entry = CustomerSupport.objects.get(
            customer_support_id=customer_support_id
        )

    return customer_support_entry


@pytest.fixture
def client():
    """Fixture for API client."""
    return APIClient()


@pytest.fixture
def auth_api_client(client, user):
    token_payload = {
        "user_id": str(user.user_id),
        "email": user.email,
        "type": "access",
    }
    from django.conf import settings

    token = jwt.encode(token_payload, settings.PRIVATE_KEY, algorithm="RS256")
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return client


@pytest.mark.django_db
def test_create_customer_support_success_without_user(client):
    """Test successful creation of a CustomerSupport entry without user reference."""
    url = reverse("customersupport-list")
    data = {
        "message": "New customer support message without user.",
        "summary": "General Inquiry",  # Fixed typo from "summart"
        "contact_email": "new_support@example.com",
        "contact_name": "John Doe",  # Adding contact_name
    }

    response = client.post(url, data, format="json")
    logging.info("Data:", response.json())

    assert response.status_code == status.HTTP_201_CREATED
    assert CustomerSupport.objects.count() == 1
    assert (
        CustomerSupport.objects.first().message
        == "New customer support message without user."
    )


@pytest.mark.django_db
def test_create_customer_support_success_with_user(auth_api_client, user):
    """
    Test successful creation of a CustomerSupport entry with user reference.
    """

    url = reverse("customersupport-list")
    data = {
        "user_ref": user.user_id,
        "message": "New customer support message with user.",
        "summary": "General Inquiry",
        "contact_email": user.email,
        "contact_name": user.first_name + user.last_name,
    }

    response = auth_api_client.post(url, data, format="json")
    logging.info("Data:", response.json())

    assert response.status_code == status.HTTP_201_CREATED
    assert CustomerSupport.objects.count() == 1
    assert (
        CustomerSupport.objects.first().message
        == "New customer support message with user."
    )


@pytest.mark.django_db
def test_create_customer_support_missing_fields(client):
    """Test creation of a CustomerSupport entry fails when required fields are missing."""
    url = reverse("customersupport-list")
    data = {
        # Missing summary and contact_email and contact_name
        "message": "Missing summary and contact_email.",
    }

    response = client.post(url, data, format="json")
    logging.info("Data:", response.json())

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in response.json()
    assert (
        response.json()["error"]
        == "contact_name, contact_email and summary are required for unauthenticated requests."
    )


@pytest.mark.django_db
def test_list_customer_support(client, customer_support):
    """Test listing of CustomerSupport entries."""
    url = reverse("customersupport-list")
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) > 0  # Ensure we have at least one entry
    assert response.data[0]["message"] == customer_support.message


@pytest.mark.django_db
def test_retrieve_customer_support(client, customer_support):
    """Test retrieving a specific CustomerSupport entry."""
    url = reverse("customersupport-detail", args=[customer_support.customer_support_id])
    response = client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.data["message"] == customer_support.message


@pytest.mark.django_db
def test_update_customer_support(client, customer_support):
    """Test updating a CustomerSupport entry."""
    url = reverse("customersupport-detail", args=[customer_support.customer_support_id])
    updated_data = {
        "message": "Updated message.",
        "summary": "Updated summary.",
        "contact_email": "updated@example.com",
        "contact_name": "Jane Doe",
    }

    response = client.put(url, updated_data, format="json")
    assert response.status_code == status.HTTP_200_OK
    customer_support.refresh_from_db()  # Refresh from DB after update

    assert customer_support.message == "Updated message."
    assert customer_support.summary == "Updated summary."
    assert customer_support.contact_email == "updated@example.com"


@pytest.mark.django_db
def test_delete_customer_support(client, customer_support):
    """Test deletion of a CustomerSupport entry."""
    url = reverse("customersupport-detail", args=[customer_support.customer_support_id])
    response = client.delete(url)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert CustomerSupport.objects.count() == 0


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        CustomerSupport.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)
