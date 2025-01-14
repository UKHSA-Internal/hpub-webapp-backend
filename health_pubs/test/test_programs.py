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
def auth_api_client_user(api_client, user):
    token_payload = {
        "user_id": str(user.user_id),
        "email": user.email,
        "type": "access",
    }
    from django.conf import settings

    token = jwt.encode(token_payload, settings.PRIVATE_KEY, algorithm="RS256")
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
    return api_client


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
def test_create_program(auth_api_client_admin, program):
    url = reverse("program-create-list")
    program_data = {
        "programme_name": "New Test Program",
        "is_featured": True,
        "is_temporary": False,
        "program_term": "short_term",
        "external_key": f"newtestprogram{str(uuid.uuid4())}",
    }

    response = auth_api_client_admin.post(url, program_data, format="json")

    assert response.status_code == status.HTTP_201_CREATED
    assert "created_programs" in response.data
    assert Program.objects.filter(programme_name="New Test Program").exists()


@pytest.mark.django_db
def test_create_program_without_name(auth_api_client_admin, program):
    url = reverse("program-create-list")
    program_data = {"is_featured": False, "program_term": "short_term"}

    response = auth_api_client_admin.post(url, program_data, format="json")

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "errors" in response.data
    assert "Program Name is required" in response.data["errors"][0]["error"]


@pytest.mark.django_db
def test_list_programs(api_client, program):
    url = reverse("program-list")

    response = api_client.get(url)

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) > 0
    assert not any(item["is_temporary"] for item in response.data)


@pytest.mark.django_db
def test_update_program(auth_api_client_admin, program):
    url = reverse("program-update-detail", kwargs={"pk": program.program_id})
    updated_data = {"programme_name": "Updated Program Name", "is_featured": True}

    response = auth_api_client_admin.patch(url, updated_data, format="json")

    assert response.status_code == status.HTTP_200_OK
    program.refresh_from_db()
    assert program.programme_name == "Updated Program Name"
    assert program.is_featured is True


@pytest.mark.django_db
def test_destroy_program(auth_api_client_admin, program):
    url = reverse("program-destroy-detail", kwargs={"pk": program.program_id})

    response = auth_api_client_admin.delete(url)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert not Program.objects.filter(program_id=program.program_id).exists()


@pytest.mark.django_db
def test_get_featured_programs(api_client, program):
    url = reverse("program-featured-programs")

    response = api_client.get(url)
    print("RESPONSE", response.json())

    assert response.status_code == status.HTTP_200_OK
    assert len(response.data) > 0
    assert all(item["is_featured"] for item in response.data)


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        Establishment.objects.all().delete()
        Organization.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Program.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)


#
