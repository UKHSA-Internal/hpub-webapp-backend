import io
import logging
import uuid

import jwt
import pandas as pd
import pytest
from core.audiences.models import Audience
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


# Utility function to create or get a parent page
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


# Utility function to create unique slugs for testing
def generate_unique_slug(base_slug, model):
    """Generate a unique slug for the Audience model."""
    queryset = model.objects.filter(slug__startswith=base_slug)
    if not queryset.exists():
        return base_slug
    num = queryset.count() + 1
    return f"{base_slug}-{num}"


@pytest.fixture
def api_client():
    return APIClient()


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


# Fixture to create multiple Audience entries for bulk tests
@pytest.fixture
def bulk_audience_data(db):
    """Fixture to create multiple sample Audience entries."""
    unique_slug_1 = generate_unique_slug(
        f"test-audience-1-{str(uuid.uuid4())}", Audience
    )
    unique_slug_2 = generate_unique_slug(
        f"test-audience-2-{str(uuid.uuid4())}", Audience
    )

    root_page = Page.objects.first()  # Assuming the root page is the first one

    audience_entry_1_id = "201"
    audience_entry_2_id = "202"

    # Create or get Audience entry 1
    if not Audience.objects.filter(audience_id=audience_entry_1_id).exists():
        audience_entry_1 = Audience(
            audience_id=audience_entry_1_id,
            title="Sample Audience 1",
            slug=slugify(unique_slug_1),
            name="Test Audience 1",
            key="test-key-2",
            description="This is a test description for entry 1.",
            content_type=ContentType.objects.get_for_model(Audience),
        )
        root_page.add_child(instance=audience_entry_1)
        audience_entry_1.save()
    else:
        audience_entry_1 = Audience.objects.get(audience_id=audience_entry_1_id)
    if not Audience.objects.filter(audience_id=audience_entry_2_id).exists():
        audience_entry_2 = Audience(
            audience_id=audience_entry_2_id,
            title="Sample Audience 2",
            slug=slugify(unique_slug_2),
            name="Test Audience 2",
            key="test-key-3",
            description="This is a test description for entry 2.",
            content_type=ContentType.objects.get_for_model(Audience),
        )
        root_page.add_child(instance=audience_entry_2)
        audience_entry_2.save()
    else:
        audience_entry_2 = Audience.objects.get(audience_id=audience_entry_2_id)

    return [audience_entry_1, audience_entry_2]


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
def audience(db, parent_page):
    """Fixture to create a sample audience."""
    slug_audience = slugify(f"test-audience-{str(uuid.uuid4())}-{str(timezone.now())}")

    # Create or get Audience
    if not Audience.objects.filter(audience_id="123").exists():
        audience_instance = Audience(
            audience_id="123",
            title="Audience Title",
            slug=slug_audience,
            name="Test Audience",
            description="This is a test audience.",
            key="test-key",
        )
        parent_page.add_child(instance=audience_instance)
        audience_instance.save()
    else:
        audience_instance = Audience.objects.get(audience_id="123")

    return audience_instance


@pytest.fixture
def parent_page(db):
    """Fixture to create a parent page for audiences."""
    # Create or get parent page
    parent_page = get_or_create_parent_page("Audiences", "audiences")

    return parent_page


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


# @pytest.mark.django_db
# def test_create_audience_positive(auth_api_client, parent_page):
#     url = reverse("audience-create-list")
#     data = {
#         "audience_id": "123",
#         "name": "Test Audience",
#         "key": "test_key",
#         "description": "Test description",
#     }
#     response = auth_api_client.post(url, data, format="json")

#     assert response.status_code == status.HTTP_201_CREATED
#     assert Audience.objects.filter(key="test_key").exists()
#     assert len(response.data) == 1


# @pytest.mark.django_db
# def test_create_audience_negative_invalid_data(auth_api_client, parent_page):
#     url = reverse("audience-create-list")
#     data = {"audience_id": "123"}  # Missing "name" and "key"
#     response = auth_api_client.post(url, data, format="json")

#     assert response.status_code == status.HTTP_400_BAD_REQUEST
#     assert "name" in response.data
#     assert "key" in response.data


@pytest.mark.django_db
def test_bulk_upload_audience_positive(api_client, parent_page):
    url = reverse("audience-bulk-upload-bulk-upload")

    # Create sample Excel file in memory
    excel_data = pd.DataFrame(
        {
            "name": ["Audience1", "Audience2"],
            "key": ["key1", "key2"],
            "description": ["Description1", "Description2"],
            "id": [1, 2],
        }
    )

    excel_file = io.BytesIO()
    try:
        with pd.ExcelWriter(excel_file, engine="xlsxwriter") as writer:
            excel_data.to_excel(writer, index=False, sheet_name="Sheet1")
        excel_file.seek(0)  # Reset file pointer
        excel_file.name = (
            "test_audience_upload.xlsx"  # Set a valid file name for compatibility
        )

        # Perform the API call
        response = api_client.post(url, {"excel_file": excel_file}, format="multipart")
        print("RESPONSE", response.data)  # Debugging purposes

        # Assert the response status code
        assert response.status_code == status.HTTP_201_CREATED

        # Assert two records were created
        assert len(response.data["created"]) == 2
        assert Audience.objects.filter(name="Audience1").exists()
        assert Audience.objects.filter(name="Audience2").exists()
    finally:
        # Ensure the in-memory file is closed
        excel_file.close()


# @pytest.mark.django_db
# def test_bulk_upload_audience_negative_missing_file(api_client):
#     url = reverse("audience-bulk-upload-bulk-upload")
#     response = api_client.post(url, {}, format="multipart")

#     assert response.status_code == status.HTTP_400_BAD_REQUEST
#     assert "error" in response.data


# @pytest.mark.django_db
# def test_bulk_upload_missing_name(api_client):
#     """Test bulk upload with missing name."""
#     data = {
#         "name": [None, "Audience 4"],
#         "key": ["test-key-4", "test-key-5"],
#         "description": ["Description for audience 3", "Description for audience 4"],
#         "id": [203, 204],
#     }
#     df = pd.DataFrame(data)
#     excel_file = io.BytesIO()
#     df.to_excel(excel_file, index=False)
#     excel_file.name = "test_audience_upload_missing_name.xlsx"
#     excel_file.seek(0)

#     response = api_client.post(
#         reverse("audience-bulk-upload-bulk-upload"), {"excel_file": excel_file}, format="multipart"
#     )

#     assert response.status_code == status.HTTP_400_BAD_REQUEST
#     assert "Missing name or key for entry" in str(response.data["errors"])


# @pytest.mark.django_db
# def test_bulk_upload_existing_key(api_client, bulk_audience_data):
#     """Test bulk upload with existing audience key."""
#     data = {
#         "name": ["Audience 1", "Audience 3"],
#         "key": ["test-key-2", "test-key-4"],  # test-key-2 already exists
#         "description": ["Description for audience 1", "Description for audience 3"],
#         "id": [203, 204],
#     }
#     df = pd.DataFrame(data)
#     excel_file = io.BytesIO()
#     df.to_excel(excel_file, index=False)
#     excel_file.name = "test_audience_upload_existing_key.xlsx"
#     excel_file.seek(0)

#     response = api_client.post(
#         reverse("audience-bulk-upload-bulk-upload"), {"excel_file": excel_file}, format="multipart"
#     )
#     logger.info('Res', response)

#     assert response.status_code == status.HTTP_400_BAD_REQUEST
#     assert len(response.data["errors"]) == 1  # One error for existing key


# @pytest.mark.django_db
# def test_bulk_delete_audience_positive(api_client, audience):

#     url = reverse("audience-bulk-delete-bulk-delete")
#     response = api_client.delete(url)

#     assert response.status_code == status.HTTP_200_OK
#     assert Audience.objects.count() == 0
#     assert "message" in response.data


# @pytest.mark.django_db
# def test_bulk_delete_audience_negative_no_entries(api_client):
#     url = reverse("audience-bulk-delete-bulk-delete")
#     response = api_client.delete(url)

#     assert response.status_code == status.HTTP_404_NOT_FOUND
#     assert "message" in response.data


# @pytest.mark.django_db
# def test_create_multiple_audiences_success(auth_api_client):
#     """Test creating multiple audiences successfully."""
#     url = reverse("audience-create-list")
#     data = [
#         {
#             "audience_id": "202",
#             "name": "Audience 2",
#             "key": "test-key-2",
#             "description": "This is another test audience.",
#         },
#         {
#             "audience_id": "203",
#             "name": "Audience 3",
#             "key": "test-key-3",
#             "description": "This is yet another test audience.",
#         },
#     ]
#     response = auth_api_client.post(url, data, format="json")

#     assert response.status_code == status.HTTP_201_CREATED
#     assert Audience.objects.filter(key="test-key-2").exists()
#     assert Audience.objects.filter(key="test-key-3").exists()


# @pytest.mark.django_db
# def test_create_audience_invalid_data(auth_api_client):
#     """Test creating an audience with invalid data."""
#     url = reverse("audience-create-list")
#     response = auth_api_client.post(
#         url,
#         {
#             "audience_id": "204",  # Missing required fields
#             "name": "",  # Invalid name
#             "key": "",
#         },
#         format="json",
#     )

#     assert response.status_code == status.HTTP_400_BAD_REQUEST
#     assert "name" in response.data
#     assert "key" in response.data


# @pytest.mark.django_db
# def test_list_audiences_positive(api_client, bulk_audience_data):
#     """Test retrieving the list of audiences with valid data."""
#     url = reverse("audience-list-list")
#     response = api_client.get(url)

#     assert response.status_code == status.HTTP_200_OK
#     assert len(response.data) == len(bulk_audience_data)  # Ensure the number of entries matches
#     assert all(
#         audience.name in [entry["name"] for entry in response.data]
#         for audience in bulk_audience_data
#     )


# @pytest.mark.django_db
# def test_list_audiences_negative_empty_data(api_client):
#     """Test retrieving the list of audiences when no data exists."""
#     url = reverse("audience-list-list")
#     Audience.objects.all().delete()  # Ensure there are no audiences in the database

#     response = api_client.get(url)

#     assert response.status_code == status.HTTP_200_OK
#     assert len(response.data) == 0  # Ensure the response is empty


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        Audience.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)
