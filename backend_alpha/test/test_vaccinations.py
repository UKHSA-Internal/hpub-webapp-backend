import logging
import uuid

import jwt
import pytest
from core.establishments.models import Establishment
from core.organizations.models import Organization
from core.programs.models import Program
from core.roles.models import Role
from core.users.models import User
from core.vaccinations.models import Vaccination
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient
from wagtail.models import Page

logger = logging.getLogger(__name__)


def generate_unique_slug(base_slug, model):
    """Generate a unique slug for the Vaccination."""
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
def vaccination(db, program):
    slug_vaccination = generate_unique_slug(
        f"test-vaccination-{str(uuid.uuid4())}-{str(timezone.now())}", Vaccination
    )

    content_type = ContentType.objects.get_for_model(Page)

    root_page, created = Page.objects.get_or_create(
        title="Root", slug="root", path="0001", depth=1, content_type=content_type
    )

    if created:
        root_page.save_revision().publish()

    vaccinations_page = get_or_create_parent_page("Vaccinations", "vaccinations")

    # Create or get Vaccination
    if not Vaccination.objects.filter(vaccination_id="1").exists():
        vaccination = Vaccination(
            title="Test Vaccination",
            slug=slugify(slug_vaccination),
            vaccination_id="1",
            name="Test Vaccination",
            key="vaccination-key",
            description="A test vaccination for unit testing.",
        )
        vaccinations_page.add_child(instance=vaccination)
        vaccination.save()
    else:
        vaccination = Vaccination.objects.get(vaccination_id="1")

    return vaccination


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
            user_id="24",
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


@pytest.mark.django_db
class TestVaccinationViewSet:
    # Positive test for creating a vaccination with program reference
    def test_create_vaccination_with_program(self, auth_api_client_admin, program):
        url = reverse("vaccination-create-list")
        logging.info("Program", program.program_id)
        data = {
            "vaccinations": [
                {
                    "vaccination_id": "100",
                    "name": "New Vaccination",
                    "key": "vaccination-key",
                    "description": "This is a new vaccination",
                    "program_names": [program.programme_name],
                }
            ]
        }
        response = auth_api_client_admin.post(url, data, format="json")
        logging.info("Response", response.json())

        assert response.status_code == status.HTTP_201_CREATED
        assert response.data[0]["name"] == "New Vaccination"

        # Compare the list of program IDs in the response to the expected list
        assert response.data[0]["programs"] == [program.program_id]

    # Negative test for creating a vaccination with non-existent program
    def test_create_vaccination_with_invalid_program(self, auth_api_client_admin):
        url = reverse("vaccination-create-list")
        data = {
            "vaccinations": [
                {
                    "vaccination_id": "101",
                    "name": "Invalid Program Vaccination",
                    "key": "invalid-key",
                    "description": "This vaccination has an invalid program",
                    "program_names": ["Non-Existent Program"],
                }
            ]
        }
        response = auth_api_client_admin.post(url, data, format="json")
        logging.info("Res", response.json())

        # Expecting a validation error since the program does not exist
        assert response.status_code == 404
        assert (
            response.data[0]["error"]
            == "Program 'Non-Existent Program' does not exist."
        )

    # Positive test for listing vaccinations with program details

    def test_list_vaccinations_with_program(self, api_client, vaccination):
        url = reverse("vaccination-list-list")
        response = api_client.get(url)

        logging.info("Res", response.json())

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) > 0
        assert response.data[0]["name"] == "Test Vaccination"

        # Check if the vaccination is linked to the correct program
        program_ids = [program.program_id for program in vaccination.programs.all()]
        assert response.data[0]["programs"] == program_ids

    # Negative test for listing vaccinations when no vaccinations with programs exist
    def test_list_vaccinations_empty_with_program(self, api_client):
        url = reverse("vaccination-list-list")
        Vaccination.objects.all().delete()  # Ensure no vaccinations are present
        response = api_client.get(url)

        assert response.status_code == status.HTTP_200_OK
        assert len(response.data) == 0

    # Positive test for deleting all vaccinations with programs
    def test_delete_all_vaccinations_with_program(self, api_client, vaccination):
        url = reverse("vaccination-delete-delete-all")
        response = api_client.delete(url)
        print("RESPONSE", response)  # for debugging

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Vaccination.objects.count() == 0

    # Negative test for deleting all vaccinations when none exist
    def test_delete_all_vaccinations_empty(self, api_client):
        url = reverse("vaccination-delete-delete-all")
        Vaccination.objects.all().delete()  # Ensure no vaccinations are present
        response = api_client.delete(url)
        logger.info("RESPONSE", response)  # for debugging

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert Vaccination.objects.count() == 0
