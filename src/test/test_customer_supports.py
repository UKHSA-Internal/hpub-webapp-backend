import logging
import uuid

import jwt
import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient
from wagtail.models import Page

from core.customer_support.models import CustomerSupport
from core.establishments.models import Establishment
from core.organizations.models import Organization
from core.roles.models import Role
from core.users.models import User

logger = logging.getLogger(__name__)


# === Helper Functions ===


def generate_unique_slug(base, model):
    """Generate a unique slug for the given model based on a base string."""
    base_slug = slugify(base)
    queryset = model.objects.filter(slug__startswith=base_slug)
    if not queryset.exists():
        return base_slug
    num = queryset.count() + 1
    return f"{base_slug}-{num}"


def get_or_create_parent_page(title, slug):
    """
    Retrieve the parent page with the given slug or create one if not found.
    The new page is created as a child of the root page.
    """
    try:
        parent_page = Page.objects.get(slug=slug)
        logger.info(f"Parent page '{title}' found with slug '{slug}'.")
    except Page.DoesNotExist:
        logger.warning(f"Parent page '{title}' not found, creating new one.")
        try:
            root_page = Page.objects.first()
            if not root_page:
                logger.exception("No root page found to attach new pages.")
            parent_page = Page(
                title=title,
                slug=slug,
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            parent_page.save_revision().publish()
            logger.info(f"Parent page '{title}' created with slug '{slug}'.")
        except Exception as ex:
            logger.error(f"Failed to create parent page '{title}': {str(ex)}")
            raise
    return parent_page


def get_or_create_model_instance(
    model, lookup_kwargs, create_instance_func, parent_title, parent_slug
):
    """
    Generic helper to either get or create an instance of a model.
    The creation function (create_instance_func) is called if an instance matching
    lookup_kwargs is not found. The new instance is attached as a child of the parent page.
    """
    instance = model.objects.filter(**lookup_kwargs).first()
    if instance:
        return instance
    parent_page = get_or_create_parent_page(parent_title, parent_slug)
    instance = create_instance_func()
    parent_page.add_child(instance=instance)
    instance.save()
    return instance


# === Fixtures ===


# Ensure a root page exists for all tests.
@pytest.fixture(scope="session", autouse=True)
def ensure_root_page(db):
    if not Page.objects.exists():
        content_type = ContentType.objects.get_for_model(Page)
        root_page = Page(title="Root", slug="root", content_type=content_type)
        # For wagtail, often the root page has pk=1. Adjust as needed.
        root_page.save()
        logger.info("Created root page for tests.")


@pytest.fixture
def organization(db):
    """Fixture to create or retrieve a sample Organization."""
    unique_base = f"test-organizations-{uuid.uuid4()}-{timezone.now()}"
    slug_org = generate_unique_slug(unique_base, Organization)

    def create_org():
        return Organization(
            title="Test Organization",
            slug=slug_org,
            organization_id="1",
            name="Test Organization",
            external_key="1234",
        )

    return get_or_create_model_instance(
        Organization,
        {"organization_id": "1"},
        create_org,
        parent_title="Organizations",
        parent_slug="organizations",
    )


@pytest.fixture
def role(db):
    """Fixture to create or retrieve a sample Role."""
    unique_base = f"test-role-{uuid.uuid4()}-{timezone.now()}"
    slug_role = generate_unique_slug(unique_base, Role)

    def create_role():
        return Role(
            title="Role Title",
            slug=slug_role,
            role_id="50",
            name="User",
        )

    return get_or_create_model_instance(
        Role,
        {"role_id": "50"},
        create_role,
        parent_title="Roles",
        parent_slug="roles",
    )


@pytest.fixture
def establishment_data(db, organization):
    """Fixture to create or retrieve a sample Establishment."""
    unique_base = f"test-establishment-{uuid.uuid4()}-{timezone.now()}"
    slug_est = generate_unique_slug(unique_base, Establishment)

    def create_est():
        return Establishment(
            establishment_id="130",
            title="Test Establishment",
            slug=slug_est,
            organization_ref=organization,
            name="Test Establishment",
        )

    return get_or_create_model_instance(
        Establishment,
        {"establishment_id": "130"},
        create_est,
        parent_title="Establishments",
        parent_slug="establishments",
    )


@pytest.fixture
def user(db, establishment_data, role):
    """Fixture to create or retrieve a sample User."""
    unique_base = f"test-user-{uuid.uuid4()}-{timezone.now()}"
    slug_user = generate_unique_slug(unique_base, User)

    def create_user():
        user_inst = User(
            title="User Title",
            slug=slug_user,
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
        user_inst.set_password("password123")
        return user_inst

    return get_or_create_model_instance(
        User,
        {"email": "testuser@example.com"},
        create_user,
        parent_title="Users",
        parent_slug="users",
    )


@pytest.fixture
def customer_support(db):
    """Fixture to create or retrieve a single CustomerSupport entry."""
    unique_base = f"test-customersupport-{uuid.uuid4()}"
    slug_cs = generate_unique_slug(unique_base, CustomerSupport)
    customer_support_id = str(uuid.uuid4())

    def create_cs():
        Page.objects.first()
        return CustomerSupport(
            customer_support_id=customer_support_id,
            title="Sample Customer Support",
            slug=slug_cs,
            user_ref=None,
            message="This is a sample message.",
            summary="General Inquiry",
            contact_email="test@example.com",
            content_type=ContentType.objects.get_for_model(CustomerSupport),
        )

    return get_or_create_model_instance(
        CustomerSupport,
        {"customer_support_id": customer_support_id},
        create_cs,
        parent_title="CustomerSupport",
        parent_slug="customersupport",
    )


@pytest.fixture
def client():
    """Fixture for APIClient."""
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


# === Tests ===


@pytest.mark.django_db
def test_create_customer_support_success_without_user(client):
    """
    Test successful creation of a CustomerSupport entry without a user reference.
    """
    url = reverse("customersupport-list")
    data = {
        "message": "New customer support message without user.",
        "summary": "General Inquiry",
        "contact_email": "new_support@example.com",
        "contact_name": "John Doe",
    }

    response = client.post(url, data, format="json")
    assert response.status_code == status.HTTP_201_CREATED
    assert CustomerSupport.objects.count() == 1
    assert (
        CustomerSupport.objects.first().message
        == "New customer support message without user."
    )


@pytest.mark.django_db
def test_create_customer_support_success_with_user(auth_api_client, user):
    """
    Test successful creation of a CustomerSupport entry with a user reference.
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
    assert response.status_code == status.HTTP_201_CREATED
    assert CustomerSupport.objects.count() == 1
    assert (
        CustomerSupport.objects.first().message
        == "New customer support message with user."
    )


@pytest.mark.django_db
def test_create_customer_support_missing_fields(client):
    """
    Test creation of a CustomerSupport entry fails when required fields are missing.
    """
    url = reverse("customersupport-list")
    data = {
        # Missing summary, contact_email and contact_name
        "message": "Missing summary and contact_email.",
    }

    response = client.post(url, data, format="json")
    resp_json = response.json()
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "error" in resp_json
    assert (
        resp_json["error"]
        == "contact_name, contact_email and summary are required for unauthenticated requests."
    )


@pytest.mark.django_db
def test_list_customer_support(client, customer_support):
    """Test listing of CustomerSupport entries."""
    url = reverse("customersupport-list")
    response = client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) > 0
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
    customer_support.refresh_from_db()
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
    """
    Teardown fixture to clean up the database after tests.
    This will remove all CustomerSupport, User, Role, and Page objects.
    """

    def teardown():
        CustomerSupport.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after tests.")

    request.addfinalizer(teardown)
