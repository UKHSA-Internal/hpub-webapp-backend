import io
import logging
import uuid

import jwt
import pandas as pd
import pytest
from core.roles.models import Role
from core.users.models import User
from core.where_to_use.models import WhereToUse
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
    """Generate a unique slug for the WhereToUse model."""
    queryset = model.objects.filter(slug__startswith=base_slug)
    if not queryset.exists():
        return base_slug

    num = queryset.count() + 1
    return f"{base_slug}-{num}"


def get_or_create_parent_page(title, slug):
    root_page = Page.objects.first()
    if not Page.objects.filter(slug=slug).exists():
        parent_page = Page(
            title=title, slug=slug, content_type=ContentType.objects.get_for_model(Page)
        )
        root_page.add_child(instance=parent_page)
        parent_page.save()
    else:
        parent_page = Page.objects.get(slug=slug)
    return parent_page


# Fixture to create a single WhereToUse entry
@pytest.fixture
def where_to_use(db):
    """Fixture to create a sample WhereToUse entry."""
    unique_slug = generate_unique_slug(
        f"test-wheretouse-{str(uuid.uuid4())}", WhereToUse
    )
    where_to_use_id = "130"  # Using a constant ID for testing

    # Check if the WhereToUse entry already exists
    if not WhereToUse.objects.filter(where_to_use_id=where_to_use_id).exists():
        root_page = Page.objects.first()  # Assuming the root page is the first one
        where_to_use_entry = WhereToUse(
            where_to_use_id=where_to_use_id,
            title="Sample Where To Use",
            slug=slugify(unique_slug),
            name="Test Where To Use",
            key="test-key-1",
            description="This is a test description.",
            content_type=ContentType.objects.get_for_model(WhereToUse),
        )
        root_page.add_child(instance=where_to_use_entry)
        where_to_use_entry.save()
    else:
        where_to_use_entry = WhereToUse.objects.get(where_to_use_id=where_to_use_id)

    return where_to_use_entry


# Fixture to create multiple WhereToUse entries
@pytest.fixture
def bulk_where_to_use_data(db):
    """Fixture to create multiple sample WhereToUse entries."""
    unique_slug_1 = generate_unique_slug(
        f"test-wheretouse-1-{str(uuid.uuid4())}", WhereToUse
    )
    unique_slug_2 = generate_unique_slug(
        f"test-wheretouse-2-{str(uuid.uuid4())}", WhereToUse
    )

    root_page = Page.objects.first()  # Assuming the root page is the first one

    # Create or get WhereToUse entry 1
    if not WhereToUse.objects.filter(where_to_use_id="131").exists():
        where_to_use_entry_1 = WhereToUse(
            where_to_use_id="131",
            title="Sample Where To Use 1",
            slug=slugify(unique_slug_1),
            name="Test Where To Use 1",
            key="test-key-2",
            description="This is a test description for entry 1.",
            content_type=ContentType.objects.get_for_model(WhereToUse),
        )
        root_page.add_child(instance=where_to_use_entry_1)
        where_to_use_entry_1.save()
    else:
        where_to_use_entry_1 = WhereToUse.objects.get(where_to_use_id="131")

    # Create or get WhereToUse entry 2
    if not WhereToUse.objects.filter(where_to_use_id="132").exists():
        where_to_use_entry_2 = WhereToUse(
            where_to_use_id="132",
            title="Sample Where To Use 2",
            slug=slugify(unique_slug_2),
            name="Test Where To Use 2",
            key="test-key-3",
            description="This is a test description for entry 2.",
            content_type=ContentType.objects.get_for_model(WhereToUse),
        )
        root_page.add_child(instance=where_to_use_entry_2)
        where_to_use_entry_2.save()
    else:
        where_to_use_entry_2 = WhereToUse.objects.get(where_to_use_id="132")

    return [where_to_use_entry_1, where_to_use_entry_2]


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
def test_create_where_to_use_success(auth_api_client):
    """Test successful creation of a WhereToUse entry."""
    url = reverse("where-to-use-create-list")
    data = {
        "name": "New Where To Use",
        "key": "new-key-1",
        "description": "This is a new test description.",
    }

    response = auth_api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert WhereToUse.objects.count() == 1
    assert WhereToUse.objects.first().name == "New Where To Use"


@pytest.mark.django_db
def test_create_where_to_use_duplicate_key(auth_api_client, where_to_use):
    """Test creating a WhereToUse entry with a duplicate key."""
    url = reverse("where-to-use-create-list")
    data = {
        "name": "Another Where To Use",
        "key": where_to_use.key,
        "description": "This description should cause a conflict.",
    }

    response = auth_api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "key" in response.data


@pytest.mark.django_db
def test_create_where_to_use_missing_fields(auth_api_client):
    """Test creating a WhereToUse entry with missing required fields."""
    url = reverse("where-to-use-create-list")
    data = {
        "key": "missing-name-key",  # Missing 'name'
    }

    response = auth_api_client.post(url, data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "name" in response.data


@pytest.mark.django_db
def test_bulk_upload_success(client):
    """Test successful bulk upload of WhereToUse entries."""
    url = reverse("where-to-use-bulk-upload-bulk-upload")

    # Prepare a mock Excel file
    df = pd.DataFrame(
        {
            "name": ["Bulk Where To Use 1", "Bulk Where To Use 2"],
            "key": ["bulk-key-1", "bulk-key-2"],
            "description": [
                "Description for bulk entry 1",
                "Description for bulk entry 2",
            ],
        }
    )
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    response = client.post(url, {"excel_file": excel_file}, format="multipart")

    assert response.status_code == status.HTTP_201_CREATED
    assert WhereToUse.objects.count() == 2


@pytest.mark.django_db
def test_bulk_upload_missing_file(client):
    """Test bulk upload without an Excel file."""
    url = reverse("where-to-use-bulk-upload-bulk-upload")

    response = client.post(url, {}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Excel file is required" in response.data["error"]


@pytest.mark.django_db
def test_bulk_upload_invalid_data(client):
    """Test bulk upload with invalid data."""
    url = reverse("where-to-use-bulk-upload-bulk-upload")

    # Prepare a mock Excel file with missing names
    df = pd.DataFrame(
        {
            "name": ["Bulk Where To Use 1", None],  # Second entry has missing name
            "key": ["bulk-key-3", "bulk-key-3"],  # Duplicate key
            "description": [
                "Description for bulk entry 1",
                "Description for bulk entry 2",
            ],
        }
    )
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False)
    excel_file.seek(0)

    response = client.post(url, {"excel_file": excel_file}, format="multipart")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert len(response.data["errors"]) == 1


@pytest.mark.django_db
def test_bulk_delete_success(client, bulk_where_to_use_data):
    """Test successful bulk deletion of WhereToUse entries."""
    url = reverse("where-to-use-bulk-delete-bulk-delete")

    # Ensure entries exist
    assert WhereToUse.objects.count() == 2  # Pre-check count

    response = client.delete(url)

    assert response.status_code == status.HTTP_200_OK
    assert "Successfully deleted" in response.data["message"]
    assert WhereToUse.objects.count() == 0  # Check if all entries are deleted


@pytest.mark.django_db
def test_bulk_delete_no_entries(client):
    """Test bulk deletion when there are no entries to delete."""
    url = reverse("where-to-use-bulk-delete-bulk-delete")

    response = client.delete(url)

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "No entries found to delete" in response.data["message"]


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        WhereToUse.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)
