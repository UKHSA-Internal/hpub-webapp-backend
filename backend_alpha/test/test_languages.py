import io
import logging
import uuid

import jwt
import pandas as pd
import pytest
from core.languages.models import LanguagePage
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
def language_page(db):
    """Fixture to create a sample language page."""
    slug_lang = generate_unique_slug(
        f"test-languages-{str(uuid.uuid4())}-{str(timezone.now())}", LanguagePage
    )

    unique_root_slug = f"root-{str(uuid.uuid4())}"
    content_type = ContentType.objects.get_for_model(Page)
    root_page = Page(title="Root", slug=unique_root_slug, content_type=content_type)
    Page.objects.get(id=1).add_child(instance=root_page)
    root_page.save()

    # Create or get parent page for languages
    languages_page = get_or_create_parent_page("Languages", "languages")

    # Create or get LanguagePage
    if not LanguagePage.objects.filter(language_id="1").exists():
        language_page = LanguagePage(
            title="Test Language",
            slug=slugify(slug_lang),
            language_id="1",
            language_names="Test Language",
            iso_language_code="tl",
        )
        languages_page.add_child(instance=language_page)
        language_page.save()
    else:
        language_page = LanguagePage.objects.get(language_id="1")

    return language_page


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


@pytest.mark.django_db
class TestLanguagePageViewSet:
    def test_create_language_success(self, auth_api_client, language_page):
        """Positive test: Create a language with valid data."""
        url = reverse("language-create-list")
        payload = {
            "languages": [{"language_name": "Japan", "iso_language_code": "ja-JP"}]
        }

        response = auth_api_client.post(url, payload, format="json")
        logging.info("RES", response.json())  # For debugging
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["created"][0]["iso_language_code"] == "ja-JP"
        assert response.data["created"][0]["language_names"] == "Japan"

    def test_create_language_duplicate(self, auth_api_client, language_page):
        """Negative test: Attempt to create a duplicate language."""
        url = reverse("language-create-list")

        # Create the initial language
        initial_data = {
            "languages": [
                {
                    "language_id": "1",
                    "language_name": "Test Language",
                    "iso_language_code": "tl",
                }
            ]
        }
        response = auth_api_client.post(url, data=initial_data, format="json")

        # Attempt to create the same language again
        response = auth_api_client.post(url, data=initial_data, format="json")
        logging.info("RES", response.json())

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert 'Language "Test Language" already exists' in response.json().get(
            "errors", [{}]
        )[0].get("error", "")

    def test_create_language_missing_name(self, auth_api_client):
        """Negative test: Attempt to create a language with missing name."""
        url = reverse("language-create-list")

        data = {
            "languages": [
                {
                    "language_id": "3",  # Valid language_id
                    "iso_language_code": "es",  # Valid iso_language_code
                    # "language_name" is intentionally omitted to test the validation
                }
            ]
        }

        response = auth_api_client.post(url, data=data, format="json")
        logging.info("RES", response.json())
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["errors"][0]["error"] == "Missing language_name"

    def test_create_language_missing_iso_code_invalid_language(
        self, auth_api_client, language_page
    ):
        """Negative test: Attempt to create a language with missing iso_language_code."""
        url = reverse("language-create-list")
        data = {"languages": [{"language_name": "Freckles"}]}

        response = auth_api_client.post(url, data=data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert (
            "Invalid language name 'Freckles', cannot derive iso_language_code."
            in response.json().get("errors", [{}])[0].get("error", "")
        )

    def test_create_multiple_languages(self, auth_api_client, language_page):
        """Positive test: Create multiple languages in a single request."""
        url = reverse("language-create-list")
        data = {
            "languages": [
                {"language_name": "Japan", "iso_language_code": "ja-JP"},
                {"language_name": "Spanish", "iso_language_code": "es-ES"},
            ]
        }

        response = auth_api_client.post(url, data=data, format="json")
        assert response.status_code == status.HTTP_201_CREATED
        assert len(response.data["created"]) == 2

    def test_create_language_missing_both_fields(
        self, auth_api_client, language_page, db
    ):
        """Negative test: Attempt to create a language with missing both language_name and iso_language_code."""
        url = reverse("language-create-list")
        data = {"languages": [{}]}  # Both fields are missing

        response = auth_api_client.post(url, data=data, format="json")
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "Missing language_name" in response.json().get("errors", [{}])[0].get(
            "error", ""
        ) or "Missing iso_language_code" in response.json().get("errors", [{}])[0].get(
            "error", ""
        )

    def test_bulk_language_upload_success(self, api_client, language_page: None):
        """Test successful bulk upload of LanguagePage entries."""
        url = reverse("language-bulk-upload-bulk-language-upload")

        # Prepare a mock Excel file
        df = pd.DataFrame(
            {
                "language_name": ["Spanish", "French"],
                "language_id": ["1", "2"],
                "iso_language_code": ["es", "fr"],
            }
        )
        excel_file = io.BytesIO()
        df.to_excel(excel_file, index=False)
        excel_file.seek(0)

        response = api_client.post(url, {"excel_file": excel_file}, format="multipart")
        logging.info("RES", response.json())

        assert response.status_code == status.HTTP_201_CREATED
        assert LanguagePage.objects.count() == 3

    def test_delete_all_languages(self, api_client, language_page):
        """Test deletion of all languages."""
        url = reverse("language-delete-all-delete-all-languages")

        response = api_client.delete(url)
        logging.info("RES", response.json())
        assert response.status_code == status.HTTP_200_OK
        assert response.data["message"].startswith("Successfully deleted")

    def test_get_languages(self, api_client, language_page):
        """Test retrieving all language pages."""
        url = reverse(
            "language-list-list"
        )  # Adjust the URL name as per your configuration

        response = api_client.get(url)

        # Validate the response status code
        assert response.status_code == status.HTTP_200_OK

        # Validate the response data
        expected_data = [
            {
                "language_id": language_page.language_id,
                "language_names": language_page.language_names,
                "iso_language_code": language_page.iso_language_code,
            }
        ]
        assert response.json() == expected_data

    def test_get_languages_no_data(self, api_client):
        """Test retrieving all language pages when no data exists."""
        url = reverse("language-list-list")

        # Make a GET request to retrieve the languages
        response = api_client.get(url)

        # Assert that the response is successful
        assert response.status_code == 200

        # Assert that the response data is in the expected format
        assert response.data == []


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        LanguagePage.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)


#
