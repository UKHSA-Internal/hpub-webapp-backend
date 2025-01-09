import json
import logging
import uuid

import jwt
import pytest
from core.establishments.models import Establishment
from core.organizations.models import Organization
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
            external_key="12345",
            organization_ref=organization,
            name="Test Establishment",
        )
        establishments_page.add_child(instance=establishment)
        establishment.save()
    else:
        establishment = Establishment.objects.get(establishment_id="130")

    return establishment


@pytest.fixture
def bulk_establishment_data(db, organization):
    """Fixture to create multiple sample establishments."""
    slug_establishment_1 = generate_unique_slug(
        f"test-establishment-1-{str(uuid.uuid4())}", Establishment
    )
    slug_establishment_2 = generate_unique_slug(
        f"test-establishment-2-{str(uuid.uuid4())}", Establishment
    )

    # Create or get parent page for establishments
    establishments_page = get_or_create_parent_page("Establishments", "establishments")

    # Create or get Establishment
    if not Establishment.objects.filter(establishment_id="131").exists():
        establishment_1 = Establishment(
            establishment_id="131",
            title="Test Establishment 1",
            slug=slugify(slug_establishment_1),
            organization_ref=organization,
            name="Test Establishment 1",
        )
        establishments_page.add_child(instance=establishment_1)
        establishment_1.save()
    else:
        establishment_1 = Establishment.objects.get(establishment_id="131")

    # Create or get Establishment
    if not Establishment.objects.filter(establishment_id="132").exists():
        establishment_2 = Establishment(
            establishment_id="132",
            title="Test Establishment 2",
            slug=slugify(slug_establishment_2),
            organization_ref=organization,
            name="Test Establishment 2",
        )
        establishments_page.add_child(instance=establishment_2)
        establishment_2.save()
    else:
        establishment_2 = Establishment.objects.get(establishment_id="132")

    return [establishment_1, establishment_2]


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
def test_bulk_create_establishments(auth_api_client, organization):
    """Test bulk creation of establishments."""
    url = reverse("establishment-bulk-create-bulk-create")

    establishment_payload = [
        {
            "establishment_id": str(uuid.uuid4()),
            "name": "New Test Establishment Name",
            "organization_ref": organization.organization_id,
            "external_key": f"newtestestablishment{str(uuid.uuid4())}",
        },
        {
            "establishment_id": str(uuid.uuid4()),
            "name": "Newer Test Establishment Name",
            "organization_ref": organization.organization_id,
            "external_key": f"newertestestablishment{str(uuid.uuid4())}",
        },
    ]

    response = auth_api_client.post(
        url, data=json.dumps(establishment_payload), content_type="application/json"
    )
    print("RES", response.json())

    assert response.status_code == status.HTTP_201_CREATED
    assert Establishment.objects.count() == len(establishment_payload)


@pytest.mark.django_db
def test_list_establishments(api_client, bulk_establishment_data):
    """Test listing all establishments."""
    url = reverse("establishment-list-list")  # Replace with your actual URL name
    response = api_client.get(url)
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == len(bulk_establishment_data)


@pytest.mark.django_db
def test_get_establishment_by_organization(auth_api_client, establishment_data):
    """Test getting establishments by organization_id."""
    url = reverse(
        "establishments-by-organization-get-by-organization"
    )  # Replace with your actual URL name
    response = auth_api_client.get(
        url, {"organization_id": establishment_data.organization_ref.organization_id}
    )  # Use organization_id
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) == 1
    assert response.json()[0]["name"] == establishment_data.name


@pytest.mark.django_db
def test_delete_all_establishments(auth_api_client, bulk_establishment_data):
    """Test the delete_all action for establishments."""

    # Ensure establishments are created
    assert Establishment.objects.count() == 2

    # Get the URL for the delete_all action
    url = reverse("establishments-bulk-delete-delete-all")

    # Send the DELETE request
    response = auth_api_client.delete(url)

    # Check the response
    assert response.status_code == status.HTTP_200_OK
    assert response.data == {"message": "Successfully deleted None establishments."}

    # Ensure all establishments have been deleted
    assert Establishment.objects.count() == 0


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        Establishment.objects.all().delete()
        Program.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)
