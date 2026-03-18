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


# === Helper Functions ===


def generate_unique_slug(base_slug, model):
    """Generate a unique slug for the given model based on the provided base_slug."""
    queryset = model.objects.filter(slug__startswith=base_slug)
    if not queryset.exists():
        return base_slug
    num = queryset.count() + 1
    return f"{base_slug}-{num}"


def get_or_create_parent_page(title, slug):
    """
    Return an existing parent Page with the given slug, or create one as a child of the root page.
    """
    if not Page.objects.filter(slug=slug).exists():
        root_page = Page.objects.first()
        parent_page = Page(
            title=title,
            slug=slug,
            content_type=ContentType.objects.get_for_model(Page),
        )
        root_page.add_child(instance=parent_page)
        parent_page.save()
    else:
        parent_page = Page.objects.get(slug=slug)
    return parent_page


def create_where_to_use_entry(
    where_to_use_id, title, name, key, description, unique_suffix=None
):
    """
    Create or retrieve a WhereToUse entry with the given parameters.
    A unique slug is generated using the provided unique_suffix (or a new uuid if None).
    The new entry is attached as a child of the root page.
    """
    unique_suffix = unique_suffix or str(uuid.uuid4())
    base_slug = f"test-wheretouse-{unique_suffix}"
    unique_slug = slugify(generate_unique_slug(base_slug, WhereToUse))
    content_type = ContentType.objects.get_for_model(WhereToUse)
    entry, created = WhereToUse.objects.get_or_create(
        where_to_use_id=where_to_use_id,
        defaults={
            "title": title,
            "slug": unique_slug,
            "name": name,
            "key": key,
            "description": description,
            "content_type": content_type,
        },
    )
    if created:
        root_page = Page.objects.first()
        root_page.add_child(instance=entry)
        entry.save()
    return entry


# === Fixtures ===


@pytest.fixture
def where_to_use(db):
    """Fixture to create (or get) a sample WhereToUse entry with a constant ID."""
    return create_where_to_use_entry(
        where_to_use_id="130",
        title="Sample Where To Use",
        name="Test Where To Use",
        key="test-key-1",
        description="This is a test description.",
    )


@pytest.fixture
def bulk_where_to_use_data(db):
    """
    Fixture to create (or get) multiple WhereToUse entries.
    Returns a list of two entries.
    """
    entry1 = create_where_to_use_entry(
        where_to_use_id="131",
        title="Sample Where To Use 1",
        name="Test Where To Use 1",
        key="test-key-2",
        description="This is a test description for entry 1.",
    )
    entry2 = create_where_to_use_entry(
        where_to_use_id="132",
        title="Sample Where To Use 2",
        name="Test Where To Use 2",
        key="test-key-3",
        description="This is a test description for entry 2.",
    )
    return [entry1, entry2]


@pytest.fixture
def role(db):
    """Fixture to create (or get) a sample Role entry."""
    slug_role = slugify(f"test-role-{uuid.uuid4()}-{timezone.now()}")
    roles_page = get_or_create_parent_page("Roles", "roles")
    if not Role.objects.filter(role_id="50").exists():
        role_instance = Role(
            title="Admin Role",
            slug=slug_role,
            role_id="50",
            name="Admin",
        )
        roles_page.add_child(instance=role_instance)
        role_instance.save()
    else:
        role_instance = Role.objects.get(role_id="50")
    return role_instance


@pytest.fixture
def user(db, role):
    """Fixture to create (or get) a sample User with admin permissions."""
    slug_user = slugify(f"test-user-{uuid.uuid4()}-{timezone.now()}")
    users_page = get_or_create_parent_page("Users", "users")
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
    """Return an APIClient instance."""
    return APIClient()


@pytest.fixture
def auth_api_client(api_client, user):
    """
    Return an authenticated APIClient with a JWT token based on the provided user.
    """
    token_payload = {
        "user_id": str(user.user_id),
        "email": user.email,
        "type": "access",
    }
    from django.conf import settings

    token = jwt.encode(token_payload, settings.PRIVATE_KEY, algorithm="RS256")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


# === Tests ===


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
    # Expect one new entry (if no other entries exist from previous tests)
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
    data = {"key": "missing-name-key"}  # Missing 'name'
    response = auth_api_client.post(url, data, format="json")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "name" in response.data


@pytest.mark.django_db
def test_bulk_upload_success(api_client):
    """Test successful bulk upload of WhereToUse entries."""
    url = reverse("where-to-use-bulk-upload-bulk-upload")
    # Prepare a mock Excel file with two entries
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
    response = api_client.post(url, {"excel_file": excel_file}, format="multipart")
    assert response.status_code == status.HTTP_201_CREATED
    # Expect two entries from the bulk upload
    assert WhereToUse.objects.count() == 2


@pytest.mark.django_db
def test_bulk_upload_missing_file(api_client):
    """Test bulk upload when no Excel file is provided."""
    url = reverse("where-to-use-bulk-upload-bulk-upload")
    response = api_client.post(url, {}, format="multipart")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "Excel file is required" in response.data["error"]


@pytest.mark.django_db
def test_bulk_upload_invalid_data(api_client):
    """Test bulk upload with invalid data."""
    url = reverse("where-to-use-bulk-upload-bulk-upload")
    # Prepare a mock Excel file with missing name and duplicate keys
    df = pd.DataFrame(
        {
            "name": ["Bulk Where To Use 1", None],  # Second entry missing name
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
    response = api_client.post(url, {"excel_file": excel_file}, format="multipart")
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    # Expect at least one error in the response
    assert len(response.data.get("errors", [])) >= 1


@pytest.mark.django_db
def test_bulk_delete_success(api_client, bulk_where_to_use_data):
    """Test successful bulk deletion of WhereToUse entries."""
    url = reverse("where-to-use-bulk-delete-bulk-delete")
    # Pre-check: expect two entries from the bulk fixture
    assert WhereToUse.objects.count() == 2
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_200_OK
    assert "Successfully deleted" in response.data["message"]
    # All entries should be deleted
    assert WhereToUse.objects.count() == 0


@pytest.mark.django_db
def test_bulk_delete_no_entries(api_client):
    """Test bulk deletion when there are no entries to delete."""
    url = reverse("where-to-use-bulk-delete-bulk-delete")
    response = api_client.delete(url)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "No entries found to delete" in response.data["message"]


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after tests."""

    def teardown():
        WhereToUse.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after tests.")

    request.addfinalizer(teardown)
