import json
import logging
import uuid

import jwt
import pytest
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

# Utility functions


def generate_unique_slug(base_slug, model):
    """Generate a unique slug for the Organization."""
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
def bulk_organization_data(db):
    """Fixture to create multiple sample organizations."""
    slug_org_1 = generate_unique_slug(
        f"test-organization-1-{str(uuid.uuid4())}", Organization
    )
    slug_org_2 = generate_unique_slug(
        f"test-organization-2-{str(uuid.uuid4())}", Organization
    )

    # Create or get parent page for organizations
    organizations_page = get_or_create_parent_page("Organizations", "organizations")

    # Create or get Organization 1
    if not Organization.objects.filter(organization_id="131").exists():
        organization_1 = Organization(
            organization_id="131",
            title="Test Organization 1",
            slug=slugify(slug_org_1),
            name="Test Organization 1",
            external_key="key-131",
        )
        organizations_page.add_child(instance=organization_1)
        organization_1.save()
    else:
        organization_1 = Organization.objects.get(organization_id="131")

    # Create or get Organization 2
    if not Organization.objects.filter(organization_id="132").exists():
        organization_2 = Organization(
            organization_id="132",
            title="Test Organization 2",
            slug=slugify(slug_org_2),
            name="Test Organization 2",
            external_key="key-132",
        )
        organizations_page.add_child(instance=organization_2)
        organization_2.save()
    else:
        organization_2 = Organization.objects.get(organization_id="132")

    return [organization_1, organization_2]


@pytest.fixture
def role(db):
    """Fixture to create a sample role."""
    slug_role = slugify(f"test-role-{str(uuid.uuid4())}-{str(timezone.now())}")

    # Create or get parent page for roles
    roles_page = get_or_create_parent_page("Roles", "roles")

    # Create or get Role
    if not Role.objects.filter(role_id="50").exists():
        role_instance = Role(
            title="Admin Role", slug=slug_role, role_id="50", name="Admin"
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


# Test cases


@pytest.mark.django_db
def test_bulk_create_organizations(auth_api_client):
    """Test bulk creation of organizations."""
    url = reverse("organization-bulk-create-bulk-create")

    organization_payload = [
        {
            "organization_id": str(uuid.uuid4()),
            "name": "Test Organization 1",
            "external_key": "test-key-1",
        },
        {
            "organization_id": str(uuid.uuid4()),
            "name": "Test Organization 2",
            "external_key": "test-key-2",
        },
    ]

    response = auth_api_client.post(
        url, data=json.dumps(organization_payload), content_type="application/json"
    )

    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["count"] == len(organization_payload)
    assert Organization.objects.count() == len(organization_payload)


@pytest.mark.django_db
def test_bulk_create_organizations_invalid_data(auth_api_client):
    """Test bulk creation with invalid data."""
    url = reverse("organization-bulk-create-bulk-create")

    response = auth_api_client.post(
        url,
        data=json.dumps({"organization": "invalid-data"}),
        content_type="application/json",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.json() == {"error": "Data must be a list of organizations."}


@pytest.mark.django_db
def test_list_organizations(api_client, organization):
    """Test listing all organizations."""
    url = reverse("organization-list-list")  # Replace with your actual URL name
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1  # Only one organization created in the fixture


@pytest.mark.django_db
def test_delete_organizations(api_client, organization):
    """Test deleting organizations."""
    url = reverse(
        "organization-delete-detail", kwargs={"pk": organization.organization_id}
    )

    response = api_client.delete(url, content_type="application/json")

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert Organization.objects.count() == 0


@pytest.mark.django_db
def test_bulk_delete_organizations(api_client, bulk_organization_data):
    """Test bulk deletion of organizations."""
    url = reverse("organization-delete-bulk-delete")

    response = api_client.delete(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"message": "Successfully deleted None entries."}
    assert Organization.objects.count() == 0  # Check if all are deleted


@pytest.mark.django_db
def test_delete_non_existent_organization(api_client):
    """Test deleting an organization that doesn't exist."""
    non_existent_id = uuid.uuid4()  # Random non-existent organization ID
    url = reverse("organization-delete-detail", kwargs={"pk": non_existent_id})

    response = api_client.delete(url, content_type="application/json")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"detail": "No Organization matches the given query."}


@pytest.mark.django_db
def test_bulk_delete_organizations_invalid_data(api_client):
    """Test bulk delete organizations with invalid data."""
    url = reverse("organization-delete-bulk-delete")

    response = api_client.delete(
        url, data=json.dumps({"ids": "invalid-data"}), content_type="application/json"
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json() == {"message": "No entries found to delete."}


@pytest.mark.django_db
def test_update_organization(auth_api_client, organization):
    """Test updating an organization."""
    url = reverse(
        "organization-update-detail", kwargs={"pk": organization.organization_id}
    )

    update_data = {"name": "Updated Test Organization", "external_key": "updated-key"}

    response = auth_api_client.put(
        url, data=json.dumps(update_data), content_type="application/json"
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["name"] == "Updated Test Organization"
    assert (
        Organization.objects.get(pk=organization.organization_id).name
        == "Updated Test Organization"
    )


@pytest.mark.django_db
def test_create_organization_missing_name(auth_api_client):
    """Test creating an organization with missing 'name' field and expecting a 400 error."""
    url = reverse("organization-bulk-create-list")

    # Wrap the payload in a dictionary with a key expected by the API
    organization_payload = {
        "organizations": [
            {
                "organization_id": str(uuid.uuid4()),
                "external_key": "test-key",  # 'name' is missing
            }
        ]
    }

    response = auth_api_client.post(
        url, data=json.dumps(organization_payload), content_type="application/json"
    )

    # Ensure the API returns a 400 Bad Request due to missing 'name'
    assert response.status_code == status.HTTP_400_BAD_REQUEST

    # Verify that the response contains the correct error message
    response_data = response.json()
    logger.info("Response Data:", response_data)  # Debugging purposes
    assert "name" in response_data
    assert response_data["name"] == ["This field is required."]


@pytest.mark.django_db
def test_get_single_organization(api_client, organization):
    """Test fetching details of a single organization."""
    url = reverse(
        "organization-list-detail", kwargs={"pk": organization.organization_id}
    )

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["organization_id"] == organization.organization_id


@pytest.mark.django_db
def test_bulk_create_organizations_with_validation(auth_api_client):
    """Test bulk creation of organizations with some missing fields."""
    url = reverse("organization-bulk-create-bulk-create")

    organization_payload = [
        {
            "organization_id": "org1",
            "name": "Valid Organization",
        },
        {
            "organization_id": None,  # Invalid organization_id
            "name": "Invalid Organization",
        },
        {
            "name": "Missing Org ID",  # Missing organization_id
        },
        {
            "organization_id": "org2",  # Valid
            "name": None,  # Invalid name
        },
    ]

    response = auth_api_client.post(
        url, data=json.dumps(organization_payload), content_type="application/json"
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "errors" in response.json()
    assert len(response.json()["errors"]) == 3  # Should capture 3 errors
    assert any(error.get("organization_id") for error in response.json()["errors"])
    assert any(error.get("name") for error in response.json()["errors"])


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        Organization.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)


#
