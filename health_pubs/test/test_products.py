import json
import logging
import os
import sys
import uuid
from unittest.mock import patch

import jwt
import pytest
from core.errors.enums import ErrorCode, ErrorMessage
from core.establishments.models import Establishment
from core.languages.models import LanguagePage
from core.organizations.models import Organization
from core.products.models import Product, ProductUpdate
from core.products.views import ProductPatchView
from core.programs.models import Program
from core.roles.models import Role
from core.users.models import User
from django.contrib.contenttypes.models import ContentType
from django.db import DatabaseError, IntegrityError, OperationalError, ProgrammingError
from django.urls import reverse
from django.utils import timezone
from django.utils.http import quote
from django.utils.text import slugify
from rest_framework import status
from rest_framework.test import APIClient
from wagtail.models import Page

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))


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
        print(f"Parent page '{title}' found with slug '{slug}'.")
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
            print(f"Parent page '{title}' created with slug '{slug}'.")
        except Exception as ex:
            logger.error(f"Failed to create parent page '{title}': {str(ex)}")
            raise
    return parent_page


@pytest.fixture
def valid_patch_data():
    return {
        "maximum_order_quantity": 100,
        "stock_owner_email_address": "test@ukhsa.gov.uk",
        "order_referral_email_address": "test.ref@ukhsa.gov.uk",
        "minimum_stock_level": 30,
        "unit_of_measure": 20,
        "run_to_zero": True,
        "available_from_choice": "specific_date",
        "order_from_date": "2024-09-01",
        "alternative_type": "Braille",
        "local_code": "0001",
        "order_end_date": "2024-12-31",
        "cost_centre": "10200",
        "summary_of_guidance": "Updated guidelines for 2024",
        "product_type": "Video",
        "product_downloads": {
            "main_download": "https://REDACTED_BUCKET_NAME.s3.eu-west-2.amazonaws.com/ukhsa_conference_image.png",
            "web_download": [
                "https://REDACTED_BUCKET_NAME.s3.eu-west-2.amazonaws.com/ukhsa_conference.mp4",
                "https://REDACTED_BUCKET_NAME.s3.eu-west-2.amazonaws.com/ukhsa_mpox.mp4",
            ],
            "video_url": "https://youtube.com/shorts/CLY1A6dAzxY?si=KpEsHreqJTVeuMc1",
        },
    }


@pytest.fixture
def invalid_patch_data():
    return {
        "product_type": "Audio",
        "product_downloads": {
            "main_download": "https://example.com/main_download.mp3",
            # Missing 'web_download' and 'transcript'
        },
        "available_from_choice": "specific_date",
        # Missing 'order_from_date'
    }


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

    # Create Program instance with unique slug
    program = Program(
        title="Test Program",
        slug=slugify(slug_program),
        program_id="2",
        programme_name="Test Program",
        is_featured=True,
        is_temporary=False,
        program_term="short_term",
    )

    if not programs_page.get_children().exists():
        program.depth = programs_page.depth + 1
        program.path = programs_page.path + "0001"
        program.numchild = 0
        program.save()
        programs_page.numchild += 1
        programs_page.save()
    else:
        programs_page.add_child(instance=program)

    program.save()

    return program


@pytest.fixture
def product(db, program):
    slug_product_one = generate_unique_slug(
        f"test-product1-{str(uuid.uuid4())}", Product
    )
    slug_product_two = generate_unique_slug(
        f"test-product2-{str(uuid.uuid4())}", Product
    )

    slug_language_one = generate_unique_slug(
        f"test-language-1-{str(uuid.uuid4())}", LanguagePage
    )
    slug_language_two = generate_unique_slug(
        f"test-language-2-{str(uuid.uuid4())}", LanguagePage
    )

    content_type = ContentType.objects.get_for_model(Page)

    root_page, created = Page.objects.get_or_create(
        title="Root", slug="root", path="0001", depth=1, content_type=content_type
    )

    if created:
        root_page.save_revision().publish()

    parent_page = get_or_create_parent_page("Products", "products")

    program = program

    language_page = get_or_create_parent_page("Languages", "languages")

    language_page_1 = LanguagePage(
        language_id="139",
        language_names="English",
        iso_language_code="en",
        title="Test Language One",
        slug=slugify(slug_language_one),
    )
    language_page.add_child(instance=language_page_1)
    language_page_1.save()

    language_page_2 = LanguagePage(
        language_id="140",
        language_names="Spanish",
        iso_language_code="es",
        title="Test Language Two",
        slug=slugify(slug_language_two),
    )
    language_page.add_child(instance=language_page_2)
    language_page_2.save()

    # Create Product instances without ProductUpdate
    product_1 = Product(
        product_title="Product 1",
        is_latest=True,
        title="Test Product 1",
        slug=slugify(slug_product_one),
        program_id=program,
        product_key="3",
        program_name="Test Program 1",
        iso_language_code="EN",
        product_code="1-3-EN-001",
        version_number=1,
        language_name="English",
        language_id=language_page_1,
        status="draft",
        tag="download-only",
        file_url="https://example.com/file1",
    )
    parent_page.add_child(instance=product_1)
    product_1.save()

    product_2 = Product(
        product_title="Product 2",
        is_latest=True,
        title="Test Product 2",
        slug=slugify(slug_product_two),
        program_id=program,
        product_key="2",
        program_name="Test Program 2",
        iso_language_code="ES",
        product_code="1-2-ES-001",
        version_number=1,
        language_name="Spanish",
        language_id=language_page_2,
        status="live",
        tag="order-only",
        file_url="https://example.com/file2",
    )
    parent_page.add_child(instance=product_2)
    product_2.save()

    return [product_1, product_2]


@pytest.fixture
def create_product_setup(db):
    # Generate unique slugs for program and products
    slug_language_one = generate_unique_slug(
        f"test-language-1-{str(uuid.uuid4())}", LanguagePage
    )
    slug_language_two = generate_unique_slug(
        f"test-language-2-{str(uuid.uuid4())}", LanguagePage
    )
    slug_program = generate_unique_slug(
        f"test-program-{str(uuid.uuid4())}-{str(timezone.now())}", Program
    )
    slug_product_one = generate_unique_slug(
        f"test-product1-{str(uuid.uuid4())}", Product
    )
    slug_product_two = generate_unique_slug(
        f"test-product2-{str(uuid.uuid4())}", Product
    )
    slug_product_update_one = generate_unique_slug(
        f"test-product1-update-{str(uuid.uuid4())}", ProductUpdate
    )
    slug_product_update_two = generate_unique_slug(
        f"test-product2-update-{str(uuid.uuid4())}", ProductUpdate
    )
    unique_root_slug = f"root-{str(uuid.uuid4())}"
    content_type = ContentType.objects.get_for_model(Page)
    root_page = Page(title="Root", slug=unique_root_slug, content_type=content_type)
    Page.objects.get(id=1).add_child(instance=root_page)
    root_page.save_revision().publish()

    programs_page = get_or_create_parent_page("Programs", "programs")
    language_page = get_or_create_parent_page("Languages", "languages")

    # Create or get Language Pages
    if not LanguagePage.objects.filter(language_id="139").exists():
        language_page_1 = LanguagePage(
            language_id="139",
            language_names="English",
            iso_language_code="en",
            title="Test Language One",
            slug=slugify(slug_language_one),
        )
        language_page.add_child(instance=language_page_1)
        language_page_1.save()
    else:
        language_page_1 = LanguagePage.objects.get(language_id="139")

    if not LanguagePage.objects.filter(language_id="140").exists():
        language_page_2 = LanguagePage(
            language_id="140",
            language_names="Spanish",
            iso_language_code="es",
            title="Test Language Two",
            slug=slugify(slug_language_two),
        )
        language_page.add_child(instance=language_page_2)
        language_page_2.save()
    else:
        language_page_2 = LanguagePage.objects.get(language_id="140")

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

    parent_page = Page(
        title="Products Update", slug="products-update", content_type=content_type
    )
    root_page.add_child(instance=parent_page)
    parent_page.save_revision().publish()

    # Create or get ProductUpdate instances
    if not ProductUpdate.objects.filter(slug=slug_product_update_one).exists():
        product_update_1 = ProductUpdate(
            minimum_stock_level=10,
            maximum_order_quantity=100,
            quantity_available=50,
            run_to_zero=False,
            available_from_choice="immediately",
            order_end_date="2024-12-31",
            alternative_type="Video and Audio",
            cost_centre="10200",
            local_code="0001",
            unit_of_measure=5,
            summary_of_guidance="Updated guidelines for 2024",
            product_type="Video",
            product_downloads={
                "main_download_url": {
                    "URL": "https://REDACTED_BUCKET_NAME.s3.amazonaws.com/ukhsa_conference_image.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=REDACTED%2F20241013%2Feu-west-2%2Fs3%2Faws4_request&X-Amz-Date=20241013T220047Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=8cd2b40cbbd8e916532234da7b9cbe7cc33d5c8164a973323a1f9a0465e09382",
                    "file_size": "31.23 KB",
                    "file_type": "image/png",
                    "dimensions": [512, 512],
                    "s3_bucket_url": "https://REDACTED_BUCKET_NAME.s3.eu-west-2.amazonaws.com/ukhsa_conference_image.png",
                },
                "video_url": "https://youtube.com/shorts/CLY1A6dAzxY?si=KpEsHreqJTVeuMc1",
                "web_download_url": [
                    {
                        "URL": "https://REDACTED_BUCKET_NAME.s3.amazonaws.com/ukhsa_conference.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=REDACTED%2F20241013%2Feu-west-2%2Fs3%2Faws4_request&X-Amz-Date=20241013T220047Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=61b239c6883171c817ed0fef7c0169e391e8fd1c0046181dbc47999e60ade99f",
                        "file_size": "21.36 MB",
                        "file_type": "video/mp4",
                        "duration": "2.50 minutes",
                        "s3_bucket_url": "https://REDACTED_BUCKET_NAME.s3.eu-west-2.amazonaws.com/ukhsa_conference.mp4",
                    },
                    {
                        "URL": "https://REDACTED_BUCKET_NAME.s3.amazonaws.com/ukhsa_mpox.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=REDACTED%2F20241013%2Feu-west-2%2Fs3%2Faws4_request&X-Amz-Date=20241013T220047Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=28806f768f3420f282ada0f8b724c592096a7439be2caa82977f7249df287d63",
                        "file_size": "2.09 MB",
                        "file_type": "video/mp4",
                        "duration": "50.83 seconds",
                        "s3_bucket_url": "https://REDACTED_BUCKET_NAME.s3.eu-west-2.amazonaws.com/ukhsa_mpox.mp4",
                    },
                ],
                "print_download_url": [],
                "transcript_url": [],
            },
            title="Update for Product 1",
            slug=slug_product_update_one,
        )
        parent_page.add_child(instance=product_update_1)
        product_update_1.save()
    else:
        product_update_1 = ProductUpdate.objects.get(slug=slug_product_update_one)

    if not ProductUpdate.objects.filter(slug=slug_product_update_two).exists():
        product_update_2 = ProductUpdate(
            minimum_stock_level=20,
            maximum_order_quantity=200,
            quantity_available=100,
            run_to_zero=False,
            available_from_choice="specific_date",
            order_from_date="2024-09-01",
            order_end_date="2024-12-31",
            unit_of_measure=1,
            product_type="Video",
            product_downloads={
                "main_download_url": {
                    "URL": "https://REDACTED_BUCKET_NAME.s3.amazonaws.com/ukhsa_conference_image.png?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=REDACTED%2F20241013%2Feu-west-2%2Fs3%2Faws4_request&X-Amz-Date=20241013T220047Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=8cd2b40cbbd8e916532234da7b9cbe7cc33d5c8164a973323a1f9a0465e09382",
                    "file_size": "31.23 KB",
                    "file_type": "image/png",
                    "dimensions": [512, 512],
                    "s3_bucket_url": "https://REDACTED_BUCKET_NAME.s3.eu-west-2.amazonaws.com/ukhsa_conference_image.png",
                },
                "video_url": "https://youtube.com/shorts/CLY1A6dAzxY?si=KpEsHreqJTVeuMc1",
                "web_download_url": [
                    {
                        "URL": "https://REDACTED_BUCKET_NAME.s3.amazonaws.com/ukhsa_conference.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=REDACTED%2F20241013%2Feu-west-2%2Fs3%2Faws4_request&X-Amz-Date=20241013T220047Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=61b239c6883171c817ed0fef7c0169e391e8fd1c0046181dbc47999e60ade99f",
                        "file_size": "21.36 MB",
                        "file_type": "video/mp4",
                        "duration": "2.50 minutes",
                        "s3_bucket_url": "https://REDACTED_BUCKET_NAME.s3.eu-west-2.amazonaws.com/ukhsa_conference.mp4",
                    },
                    {
                        "URL": "https://REDACTED_BUCKET_NAME.s3.amazonaws.com/ukhsa_mpox.mp4?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Credential=REDACTED%2F20241013%2Feu-west-2%2Fs3%2Faws4_request&X-Amz-Date=20241013T220047Z&X-Amz-Expires=3600&X-Amz-SignedHeaders=host&X-Amz-Signature=28806f768f3420f282ada0f8b724c592096a7439be2caa82977f7249df287d63",
                        "file_size": "2.09 MB",
                        "file_type": "video/mp4",
                        "duration": "50.83 seconds",
                        "s3_bucket_url": "https://REDACTED_BUCKET_NAME.s3.eu-west-2.amazonaws.com/ukhsa_mpox.mp4",
                    },
                ],
                "print_download_url": [],
                "transcript_url": [],
            },
            alternative_type="Braille",
            cost_centre="22820",
            local_code="1100",
            summary_of_guidance="Updated guidelines for 2024",
            title="Update for Product 2",
            slug=slug_product_update_two,
        )
        parent_page.add_child(instance=product_update_2)
        product_update_2.save()
    else:
        product_update_2 = ProductUpdate.objects.get(slug=slug_product_update_two)

    parent_page = Page(title="Products", slug="products", content_type=content_type)
    root_page.add_child(instance=parent_page)
    parent_page.save_revision().publish()

    # Create or get Product instances
    if not Product.objects.filter(product_id="4677686-678888").exists():
        product_1 = Product(
            product_id="4677686-678888",
            product_title="Product 1",
            is_latest=True,
            title="Test Product 1",
            slug=slug_product_one,
            program_id=program,
            product_key="5",
            program_name="Test Program 1",
            language_name="English",
            language_id=language_page_1,
            iso_language_code="EN",
            product_code="1-1-EN-001",
            version_number=1,
            status="draft",
            tag="download-only",
            file_url="https://example.com/file1",
            update_ref=product_update_1,
        )
        parent_page.add_child(instance=product_1)
        product_1.save()
    else:
        product_1 = Product.objects.get(product_id="4677686-678888")

    if not Product.objects.filter(product_id="466645486-6788888").exists():
        product_2 = Product(
            product_id="466645486-6788888",
            product_title="Product 2",
            is_latest=True,
            title="Test Product 2",
            slug=slug_product_two,
            program_id=program,
            product_key="6",
            program_name="Test Program 2",
            language_id=language_page_2,
            language_name="Spanish",
            iso_language_code="ES",
            product_code="1-2-ES-001",
            version_number=1,
            status="live",
            tag="order-only",
            file_url="https://example.com/file2",
            update_ref=product_update_2,
        )
        parent_page.add_child(instance=product_2)
        product_2.save()
    else:
        product_2 = Product.objects.get(product_id="466645486-6788888")

    return [product_1, product_2]


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
class TestProductAdminListView:
    def test_product_list_admin_successful(
        self, create_product_setup, auth_api_client_admin
    ):
        response = auth_api_client_admin.get(reverse("list-products-admin"))

        # print("RES", response.json())

        assert response.status_code == status.HTTP_200_OK

        response_data = response.json()
        assert len(response_data) == 3
        assert response_data["results"][0]["product_title"] == "Product 1"
        assert response_data["results"][1]["product_title"] == "Product 2"

    def test_product_list_admin_no_latest_products(self, auth_api_client_admin):
        Product.objects.all().delete()
        response = auth_api_client_admin.get(reverse("list-products-admin"))
        assert response.status_code == status.HTTP_404_NOT_FOUND

        response_data = response.json()
        assert response_data["error_code"] == ErrorCode.PRODUCT_NOT_FOUND.value
        assert response_data["error_message"] == ErrorMessage.PRODUCT_NOT_FOUND.value

    @patch("core.products.views.Product.objects.filter")
    def test_product_list_admin_database_error(
        self, mock_filter, auth_api_client_admin
    ):
        mock_filter.side_effect = DatabaseError("Database error")
        response = auth_api_client_admin.get(reverse("list-products-admin"))
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        response_data = response.json()
        assert response_data["error_code"] == ErrorCode.DATABASE_ERROR.value
        assert response_data["error_message"] == ErrorMessage.DATABASE_ERROR.value

    @patch("core.products.views.Product.objects.filter")
    def test_product_list_admin_timeout_error(self, mock_filter, auth_api_client_admin):
        mock_filter.side_effect = TimeoutError("Timeout error")
        response = auth_api_client_admin.get(reverse("list-products-admin"))
        assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT

        response_data = response.json()
        assert response_data["error_code"] == ErrorCode.TIMEOUT_ERROR.value
        assert response_data["error_message"] == ErrorMessage.TIMEOUT_ERROR.value

    @patch("core.products.views.Product.objects.filter")
    def test_product_list_admin_unexpected_error(
        self, mock_filter, auth_api_client_admin
    ):
        mock_filter.side_effect = Exception("Unexpected error")
        response = auth_api_client_admin.get(reverse("list-products-admin"))
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        response_data = response.json()
        assert response_data["error_code"] == ErrorCode.INTERNAL_SERVER_ERROR.value
        assert (
            response_data["error_message"] == ErrorMessage.INTERNAL_SERVER_ERROR.value
        )


@pytest.mark.django_db
class TestProductUsersListView:
    def test_product_list_users_successful(
        self, create_product_setup, auth_api_client_user
    ):
        response = auth_api_client_user.get(reverse("list-products-user"))

        assert response.status_code == status.HTTP_200_OK

        response_data = response.json()
        # print("RES", response.json())
        # Only one product has status = "live"
        assert len(response_data) == 3
        assert response_data["results"][0]["product_title"] == "Product 2"
        assert response_data["results"][0]["status"] == "live"

    def test_product_list_users_no_live_products(self, auth_api_client_user):
        # Set all products to a status other than "live"
        Product.objects.filter(status="live").update(status="draft")
        response = auth_api_client_user.get(reverse("list-products-user"))

        assert response.status_code == status.HTTP_404_NOT_FOUND

        response_data = response.json()
        assert response_data["error_code"] == ErrorCode.PRODUCT_NOT_FOUND.value
        assert response_data["error_message"] == ErrorMessage.PRODUCT_NOT_FOUND.value

    @patch("core.products.views.Product.objects.filter")
    def test_product_list_users_database_error(self, mock_filter, auth_api_client_user):
        mock_filter.side_effect = DatabaseError("Database error")
        response = auth_api_client_user.get(reverse("list-products-user"))
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        response_data = response.json()
        assert response_data["error_code"] == ErrorCode.DATABASE_ERROR.value
        assert response_data["error_message"] == ErrorMessage.DATABASE_ERROR.value

    @patch("core.products.views.Product.objects.filter")
    def test_product_list_users_timeout_error(self, mock_filter, auth_api_client_user):
        mock_filter.side_effect = TimeoutError("Timeout error")
        response = auth_api_client_user.get(reverse("list-products-user"))
        assert response.status_code == status.HTTP_504_GATEWAY_TIMEOUT

        response_data = response.json()
        assert response_data["error_code"] == ErrorCode.TIMEOUT_ERROR.value
        assert response_data["error_message"] == ErrorMessage.TIMEOUT_ERROR.value

    @patch("core.products.views.Product.objects.filter")
    def test_product_list_users_unexpected_error(
        self, mock_filter, auth_api_client_user
    ):
        mock_filter.side_effect = Exception("Unexpected error")
        response = auth_api_client_user.get(reverse("list-products-user"))
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR

        response_data = response.json()
        assert response_data["error_code"] == ErrorCode.INTERNAL_SERVER_ERROR.value
        assert (
            response_data["error_message"] == ErrorMessage.INTERNAL_SERVER_ERROR.value
        )


@pytest.mark.django_db
class TestProductPatch:
    def test_product_patch_success(
        self, product, valid_patch_data, auth_api_client_admin
    ):
        url = reverse("update-product-detail", args=[product[0].product_code])
        response = auth_api_client_admin.patch(
            url, data=json.dumps(valid_patch_data), content_type="application/json"
        )
        print("RES", response.json())

        assert response.status_code == status.HTTP_200_OK
        product[0].refresh_from_db()
        assert product[0].update_ref.product_type == "Video"

    @patch("core.products.views.Product.objects.filter")
    def test_product_not_found(
        self, mock_filter, valid_patch_data, auth_api_client_admin
    ):
        mock_filter.return_value.order_by.return_value.first.return_value = None
        response = auth_api_client_admin.patch(
            reverse("update-product-detail", args=[quote("INVALID123")]),
            data=json.dumps(valid_patch_data),
            content_type="application/json",
        )
        # print("RES", response.json())
        assert response.status_code == 404
        assert response.json() == {"error": "Product not found."}

    def test_invalid_patch_data(
        self, product, invalid_patch_data, auth_api_client_admin
    ):
        url = reverse("update-product-detail", args=[product[0].product_code])
        response = auth_api_client_admin.patch(
            url, data=json.dumps(invalid_patch_data), content_type="application/json"
        )
        # print("RES", response.json())

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "error" in response.json()

    def test_database_error(
        self, product, valid_patch_data, monkeypatch, auth_api_client_admin
    ):
        # Simulate a database error
        def mock_get_product(self, product_code):
            raise DatabaseError("Database error occurred.")

        monkeypatch.setattr(ProductPatchView, "get_product", mock_get_product)

        url = reverse("update-product-detail", args=[product[0].product_code])
        response = auth_api_client_admin.patch(
            url, data=json.dumps(valid_patch_data), content_type="application/json"
        )

        # print("RES", response.json())
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert response.json() == {
            "error": "A database error occurred, with error: Database error occurred.."
        }


@pytest.mark.django_db
class TestProductCreateView:
    def test_create_product_success(self, product, program, auth_api_client_admin):
        # Prepare the payload for creating a product
        payload = {
            "product_title": "New Test Product",
            "language_id": str(
                product[0].language_id.language_id
            ),  # Use the language ID from the fixture
            "file_url": "https://example.com/new_file",
            "program_name": program.programme_name,
            "tag": "download-only",
            "is_uuid": True,
        }

        # Send a POST request to the ProductCreateView
        response = auth_api_client_admin.post(
            reverse("create-product"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        # Check that the response is a success
        assert response.status_code == status.HTTP_201_CREATED

        # Check that the product was created in the database
        created_product = Product.objects.get(product_title=payload["product_title"])
        assert created_product.product_title == payload["product_title"]
        assert created_product.file_url == payload["file_url"]
        assert (
            created_product.language_id.language_names
            == product[0].language_id.language_names
        )

    def test_create_product_missing_fields(self, auth_api_client_admin):
        # Prepare the payload with missing fields
        payload = {
            "product_title": "New Test Product",
            "language_id": "",  # Missing language_id
            "file_url": "https://example.com/new_file",
            "program_name": "Some Program",
            "tag": "download-only",
        }

        # Send a POST request to the ProductCreateView
        response = auth_api_client_admin.post(
            reverse("create-product"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        # Check that the response indicates a bad request
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "error_code": ErrorCode.MISSING_FIELD.value,
            "error_message": ErrorMessage.MISSING_FIELD.value,
        }

    def test_create_product_invalid_program(self, product, auth_api_client_admin):
        # Prepare the payload with an invalid program name
        payload = {
            "product_title": "New Test Product",
            "language_id": str(product[0].language_id.language_id),
            "file_url": "https://example.com/new_file",
            "program_name": "Invalid Program Name",  # Invalid program name
            "tag": "download-only",
        }

        # Send a POST request to the ProductCreateView
        response = auth_api_client_admin.post(
            reverse("create-product"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        # Check that the response indicates invalid data
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "error_code": "INVALID_DATA",
            "error_message": "{'detail': 'Program name does not exist'}",
        }

    def test_create_product_language_not_found(self, program, auth_api_client_admin):
        # Prepare the payload with a non-existing language_id
        payload = {
            "product_title": "New Test Product",
            "language_id": str(uuid.uuid4()),  # Non-existing language ID
            "file_url": "https://example.com/new_file",
            "program_name": program.programme_name,
            "tag": "download-only",
        }

        # Send a POST request to the ProductCreateView
        response = auth_api_client_admin.post(
            reverse("create-product"),
            data=json.dumps(payload),
            content_type="application/json",
        )

        # Check that the response indicates invalid data
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "error_code": "INVALID_DATA",
            "error_message": "{'detail': 'Language ID does not exist'}",
        }


@pytest.mark.django_db
class TestProductSearchAdminView:
    @pytest.fixture(autouse=True)
    def setup(self, create_product_setup):
        self.products = create_product_setup
        self.program_name = "Test Program"

    def test_search_product_by_code(self, auth_api_client_admin):
        # Test search by product code
        product_code = self.products[0].product_code
        response = auth_api_client_admin.get(
            reverse("product-search-admin"), {"product_code": product_code}
        )

        print("RES", response.json())
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 4
        assert response.data["count"] == 1
        assert (
            response.data["results"]["product_info"][0]["product_code"] == product_code
        )

    def test_search_product_by_title(self, auth_api_client_admin):
        # Test search by product title
        product_title = self.products[0].product_title
        response = auth_api_client_admin.get(
            reverse("product-search-admin"), {"product_title": product_title}
        )

        print("RES", response.json())
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 4
        assert response.data["count"] == 1
        assert (
            response.data["results"]["product_info"][0]["product_title"]
            == product_title
        )

    def test_search_nonexistent_product(self, auth_api_client_admin):
        # Test searching for a nonexistent product code
        response = auth_api_client_admin.get(
            reverse("product-search-admin"), {"product_code": "NON_EXISTENT_CODE"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.data == {"detail": "No products found."}

    def test_invalid_query_param(self, auth_api_client_admin):
        # Test invalid query parameter
        response = auth_api_client_admin.get(
            reverse("product-search-admin"), {"product_code": "!!!"}
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "error_code": "INVALID_QUERY_PARAM",
            "error_message": "Invalid query parameter provided.",
        }

    def test_program_name_exists(self):
        # Check if the program name exists in the programs table
        program_exists = Program.objects.filter(
            programme_name=self.program_name
        ).exists()

        if not program_exists:
            pytest.fail(
                f"Program '{self.program_name}' does not exist in the programs table."
            )


@pytest.mark.django_db
class TestProductSearchViewForUsers:
    @pytest.fixture(autouse=True)
    def setup(self, create_product_setup):
        self.products = create_product_setup
        self.program_name = "Test Program"

    def test_search_product_by_code(self, auth_api_client_user):
        # Test search by product code where status is "live"
        product_code = self.products[
            1
        ].product_code  # Select product with "live" status
        response = auth_api_client_user.get(
            reverse("product-search-user"), {"product_code": product_code}
        )

        print("RES", response.json())
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 3
        assert response.data["count"] == 1
        assert (
            response.data["results"]["product_info"][0]["product_code"] == product_code
        )
        assert response.data["results"]["product_info"][0]["status"] == "live"

    def test_search_product_by_title(self, auth_api_client_user):
        # Test search by product title where status is "live"
        product_title = self.products[
            1
        ].product_title  # Select product with "live" status
        response = auth_api_client_user.get(
            reverse("product-search-user"), {"product_title": product_title}
        )

        print("RES", response.json())
        assert response.status_code == status.HTTP_200_OK
        assert "results" in response.data
        assert len(response.data["results"]) == 3
        assert response.data["count"] == 1
        assert (
            response.data["results"]["product_info"][0]["product_title"]
            == product_title
        )
        assert response.data["results"]["product_info"][0]["status"] == "live"

    def test_search_nonexistent_product(self, auth_api_client_user):
        # Test searching for a nonexistent product code
        response = auth_api_client_user.get(
            reverse("product-search-user"), {"product_code": "NON_EXISTENT_CODE"}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "No products found."}

    def test_invalid_query_param(self, auth_api_client_user):
        # Test invalid query parameter
        response = auth_api_client_user.get(
            reverse("product-search-user"), {"product_code": "!!!"}
        )

        print("RESPONSE", response.json())
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "error_code": "INVALID_QUERY_PARAM",
            "error_message": "Invalid query parameter provided.",
        }

    def test_program_name_exists(self):
        # Check if the program name exists in the programs table
        program_exists = Program.objects.filter(
            programme_name=self.program_name
        ).exists()

        if not program_exists:
            pytest.fail(
                f"Program '{self.program_name}' does not exist in the programs table."
            )

    @pytest.mark.parametrize(
        "query_param, expected_status, expected_response",
        [
            (
                {"product_code": "NON_EXISTENT_CODE"},
                status.HTTP_404_NOT_FOUND,
                {"detail": "No products found."},
            ),
            (
                {"product_code": "!!!"},
                status.HTTP_400_BAD_REQUEST,
                {
                    "error_code": "INVALID_QUERY_PARAM",
                    "error_message": "Invalid query parameter provided.",
                },
            ),
        ],
    )
    def test_search_edge_cases(
        self, auth_api_client_user, query_param, expected_status, expected_response
    ):
        # Test edge cases like invalid or non-existent parameters
        response = auth_api_client_user.get(reverse("product-search-user"), query_param)
        assert response.status_code == expected_status
        assert response.json() == expected_response


@pytest.mark.django_db
class TestProductDetailView:
    @pytest.fixture(autouse=True)
    def setup(self, create_product_setup):
        """Set up products using the create_product_setup fixture."""
        self.products = create_product_setup

    def test_product_detail_view_success(self, auth_api_client_user):
        """Test successful product detail view response."""
        product_1, product_2 = self.products

        # URL for the ProductDetailView
        url = reverse("product-detail", args=[product_1.product_code])
        print("update_ref", product_1.update_ref)

        # # Mock the find_similar_products function to return a list of similar products
        # with patch(
        #     "core.utils.get_product_similarity.find_similar_products"
        # ) as mock_find_similar:
        #     mock_find_similar.return_value = [
        #         {
        #             "product_title": product_2.product_title,
        #             "product_code": product_2.product_code,
        #         }
        #     ]

        response = auth_api_client_user.get(url)
        print("Response status code:", response.status_code)
        print("Response data:", response.json())

        # Assertions
        assert response.status_code == 200
        data = response.json()
        assert data["product_title"] == product_1.product_title

    def test_product_detail_view_product_not_found(self, auth_api_client_user):
        """Test product detail view with invalid product_code."""
        response = auth_api_client_user.get(
            reverse("product-detail", kwargs={"product_code": "INVALID_CODE"})
        )
        assert response.status_code == 404

        # Check the structure of the error response
        response_data = response.json()
        assert response_data["error_code"] == "PRODUCT_NOT_FOUND"

    @patch("core.products.models.Product.objects.filter")
    def test_product_detail_view_database_error(
        self, mock_filter, auth_api_client_user
    ):
        """Simulate a database error during product retrieval."""
        mock_filter.side_effect = DatabaseError("Database error occurred")

        response = auth_api_client_user.get(
            reverse(
                "product-detail", kwargs={"product_code": self.products[0].product_code}
            )
        )

        assert response.status_code == 500
        response_data = response.json()
        assert response_data["error_code"] == "DATABASE_ERROR"

    @patch("core.products.models.Product.objects.filter")
    def test_product_detail_view_timeout_error(self, mock_filter, auth_api_client_user):
        """Simulate a timeout error during product retrieval."""
        mock_filter.side_effect = TimeoutError("Timeout error occurred")

        response = auth_api_client_user.get(
            reverse(
                "product-detail", kwargs={"product_code": self.products[0].product_code}
            )
        )

        assert response.status_code == 504
        response_data = response.json()
        assert response_data["error_code"] == "TIMEOUT_ERROR"

    @patch("core.products.models.Product.objects.filter")
    def test_product_detail_view_unexpected_error(
        self, mock_filter, auth_api_client_user
    ):
        """Simulate an unexpected error during product retrieval."""
        mock_filter.side_effect = Exception("Unexpected error occurred")

        response = auth_api_client_user.get(
            reverse(
                "product-detail", kwargs={"product_code": self.products[0].product_code}
            )
        )

        assert response.status_code == 500
        response_data = response.json()
        assert response_data["error_code"] == "INTERNAL_SERVER_ERROR"


@pytest.mark.django_db
class TestProductStatusUpdateView:
    @pytest.fixture(autouse=True)
    def setup(self, create_product_setup):
        self.product_1 = create_product_setup

    def test_product_status_update_success(self, auth_api_client_admin):
        product = self.product_1[0]
        url = reverse("product-status-update", args=[product.product_code])

        payload = {"status": "live"}
        print("Payload:", payload)

        response = auth_api_client_admin.put(url, data=payload, format="json")
        print("Response status code:", response.status_code)
        print("Response data:", response.json())

        assert response.status_code == 200
        data = response.json()
        assert data["message"] == "Product status updated successfully."

        product.refresh_from_db()
        print("Updated product status:", product.status)
        assert product.status == "live"

    def test_product_status_update_product_not_found(self, auth_api_client_admin):
        url = reverse("product-status-update", args=["invalid-code"])

        payload = {"status": "live"}
        print("Payload:", payload)

        response = auth_api_client_admin.put(url, data=payload, format="json")
        print("Response status code:", response.status_code)
        print("Response data:", response.json())

        assert response.status_code == 404
        response_data = response.json()
        assert response_data["error_message"] == "The specified product does not exist."

    def test_product_status_update_invalid_status(self, auth_api_client_admin):
        product = self.product_1[0]
        url = reverse("product-status-update", args=[product.product_code])

        payload = {"status": "invalid_status"}
        print("Payload:", payload)

        response = auth_api_client_admin.put(url, data=payload, format="json")
        print("Response status code:", response.status_code)
        print("Response data:", response.json())

        assert response.status_code == 400
        response_data = response.json()
        assert response_data["error_message"] == "The status value is invalid."

    def test_product_status_update_invalid_transition(self, auth_api_client_admin):
        product = self.product_1[0]
        product.status = "withdrawn"
        product.save()
        print("Initial product status:", product.status)

        url = reverse("product-status-update", args=[product.product_code])

        payload = {"status": "live"}
        print("Payload:", payload)

        response = auth_api_client_admin.put(url, data=payload, format="json")
        print("Response status code:", response.status_code)
        print("Response data:", response.json())

        assert response.status_code == 400
        response_data = response.json()
        assert response_data["error_message"] == "The status transition is invalid."

    @pytest.mark.parametrize(
        "missing_field, expected_message",
        [
            (None, "Product status updated successfully."),
            ("language_id", "Cannot change status to 'live' due to missing fields."),
        ],
    )
    def test_product_status_update_live_missing_required_field(
        self, missing_field, expected_message, auth_api_client_admin
    ):
        product = self.product_1[0]
        url = reverse("product-status-update", args=[product.product_code])

        payload = {"status": "live"}
        print("Payload:", payload)

        with patch(
            "core.products.views.ProductStatusUpdateView.check_required_fields"
        ) as mock_check_required_fields:
            mock_check_required_fields.return_value = (
                [missing_field] if missing_field else []
            )

            response = auth_api_client_admin.put(url, data=payload, format="json")
            print("Response status code:", response.status_code)
            print("Response data:", response.json())

            response_data = response.json()
            if missing_field:
                assert response.status_code == 400
                assert expected_message in response_data["error"]
                assert missing_field in response_data.get("missing_fields", [])
            else:
                assert response.status_code == 200
                assert response_data["message"] == expected_message

    @pytest.mark.parametrize(
        "error_type, expected_status, expected_message",
        [
            (DatabaseError, 500, "A database error occurred."),
            (OperationalError, 500, "A database error occurred."),
            (IntegrityError, 500, "A database error occurred."),
            (ProgrammingError, 500, "A database error occurred."),
        ],
    )
    @patch("core.products.models.Product.objects.filter")
    def test_product_status_update_database_error(
        self,
        mock_filter,
        error_type,
        expected_status,
        expected_message,
        auth_api_client_admin,
    ):
        mock_filter.side_effect = error_type("A database error occurred.")

        product = self.product_1[0]
        url = reverse("product-status-update", args=[product.product_code])
        payload = {"status": "live"}
        print("Payload:", payload)

        response = auth_api_client_admin.put(url, data=payload, format="json")
        print("Response status code:", response.status_code)
        print("Response data:", response.json())

        response_data = response.json()
        assert response.status_code == expected_status
        assert response_data["error_message"] == expected_message

    @patch("core.products.models.Product.objects.filter")
    def test_product_status_update_timeout_error(
        self, mock_filter, auth_api_client_admin
    ):
        mock_filter.side_effect = TimeoutError("Timeout error occurred")

        product = self.product_1[0]
        url = reverse("product-status-update", args=[product.product_code])
        payload = {"status": "live"}
        print("Payload:", payload)

        response = auth_api_client_admin.put(url, data=payload, format="json")
        print("Response status code:", response.status_code)
        print("Response data:", response.json())

        response_data = response.json()
        assert response.status_code == 504
        assert response_data["error_message"] == "A timeout error occurred."

    @patch("core.products.models.Product.objects.filter")
    def test_product_status_update_unexpected_error(
        self, mock_filter, auth_api_client_admin
    ):
        mock_filter.side_effect = Exception("Unexpected error occurred")

        product = self.product_1[0]
        url = reverse("product-status-update", args=[product.product_code])
        payload = {"status": "live"}
        print("Payload:", payload)

        response = auth_api_client_admin.put(url, data=payload, format="json")
        print("Response status code:", response.status_code)
        print("Response data:", response.json())

        response_data = response.json()
        assert response.status_code == 500
        assert response_data["error_message"] == "An internal server error occurred."


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        Establishment.objects.all().delete()
        Organization.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Product.objects.all().delete()
        ProductUpdate.objects.all().delete()
        Program.objects.all().delete()
        Page.objects.all().delete()
        print("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)


#
