import logging
import uuid

import jwt
import pytest
from core.diseases.models import Disease
from core.programs.models import Program
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
def program(db):
    slug_program = generate_unique_slug(
        f"test-program-{str(uuid.uuid4())}-{str(timezone.now())}", Program
    )

    content_type = ContentType.objects.get_for_model(Page)

    root_page, created = Page.objects.get_or_create(
        title="Root", slug="root", path="0001", depth=1, content_type=content_type
    )

    if created:
        root_page.save_revision().publish()

    programs_page = get_or_create_parent_page("Programs", "programs")

    # Create or get Program
    if not Program.objects.filter(program_id="2").exists():
        program = Program(
            title="Test Program",
            slug=slugify(slug_program),
            program_id="2",
            programme_name="Test Program",
            is_featured=True,
            program_term="short_term",
        )
        programs_page.add_child(instance=program)
        program.save()
    else:
        program = Program.objects.get(program_id="2")

    return program


@pytest.fixture
def disease(db, program):
    slug_disease = generate_unique_slug(
        f"test-disease-{str(uuid.uuid4())}-{str(timezone.now())}", Disease
    )

    content_type = ContentType.objects.get_for_model(Page)

    root_page, created = Page.objects.get_or_create(
        title="Root", slug="root", path="0001", depth=1, content_type=content_type
    )

    if created:
        root_page.save_revision().publish()

    diseases_page = get_or_create_parent_page("Diseases", "diseases")

    # Create or get Disease
    if not Disease.objects.filter(disease_id="1").exists():
        disease = Disease(
            title="Test Disease",
            slug=slugify(slug_disease),
            disease_id="1",
            name="Test Disease",
            key="disease-key",
            description="A test disease for unit testing.",
        )
        diseases_page.add_child(instance=disease)
        disease.save()
    else:
        disease = Disease.objects.get(disease_id="1")

    return disease


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
class TestDiseaseViewSet:

    # Positive test for creating a disease with program reference
    def test_create_disease_with_program(self, auth_api_client, program):
        url = reverse("disease-create-list")
        data = {
            "diseases": [
                {
                    "disease_id": "101",
                    "name": "New Disease",
                    "key": "disease-key",
                    "description": "This is a new disease",
                    "program_names": [program.programme_name],
                }
            ]
        }
        response = auth_api_client.post(url, data, format="json")
        logging.info("Response", response.json())

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data[0]["name"] == "New Disease"
        assert response.data[0]["programs"] == [program.program_id]

    # Negative test for creating a disease with non-existent program
    def test_create_disease_with_invalid_program(self, auth_api_client):
        url = reverse("disease-create-list")
        data = {
            "diseases": [
                {
                    "disease_id": "101",
                    "name": "Invalid Program Disease",
                    "key": "invalid-key",
                    "description": "This disease has an invalid program",
                    "program_names": ["Non-Existent Program"],
                }
            ]
        }
        response = auth_api_client.post(url, data, format="json")
        logging.info("Res", response.json())

        # Expecting a validation error since the program does not exist
        assert response.status_code == 404
        assert (
            response.data[0]["error"]
            == "Program 'Non-Existent Program' does not exist."
        )

    # Positive test for listing diseases with program details
    def test_list_diseases_with_program(self, api_client, disease):
        url = reverse("disease-list-list")
        response = api_client.get(url)

        logging.info("Res", response.json())  # For debugging

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) > 0
        assert response.data[0]["name"] == "Test Disease"
        assert response.data[0]["programs"] == [
            program.program_id for program in disease.programs.all()
        ]

    # Positive test for deleting all diseases with programs
    def test_delete_all_diseases_with_program(self, api_client, disease):
        url = reverse("disease-delete-all-delete-all")
        response = api_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Disease.objects.count() == 0

    # Negative test for deleting all diseases when none exist
    def test_delete_all_diseases_empty(self, api_client):
        url = reverse("disease-delete-all-delete-all")
        Disease.objects.all().delete()  # Ensure no diseases are present
        response = api_client.delete(url)

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Disease.objects.count() == 0


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        Disease.objects.all().delete()
        Program.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)


#
