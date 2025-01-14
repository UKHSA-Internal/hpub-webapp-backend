import logging
import uuid

import jwt
import pytest
from core.languages.models import LanguagePage
from core.order_limits.models import OrderLimitPage
from core.organizations.models import Organization
from core.products.models import Product, ProductUpdate
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
def product(db):
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
            unit_of_measure=5,
            maximum_order_quantity=100,
            quantity_available=50,
            available_from_choice="immediately",
            order_end_date="2024-12-31",
            alternative_type="Video and Audio",
            cost_centre="10200",
            local_code="0001",
            summary_of_guidance="Updated guidelines for 2024",
            product_type="Audio",
            product_downloads={
                "main_download_url": [
                    {
                        "URL": "https://s3.amazonaws.com/bucket-name/random-file-1.png",
                        "file_size": "Unknown",
                        "file_type": "png",
                        "number_of_pages": "Not applicable",
                        "page_size": "Not applicable",
                        "dimensions": "Not applicable",
                        "duration": "Not applicable",
                        "number_of_slides": "Not applicable",
                        "number_of_paragraphs": "Not applicable",
                    },
                    {
                        "URL": "https://s3.amazonaws.com/bucket-name/random-file-2.jpg",
                        "file_size": "Unknown",
                        "file_type": "jpg",
                        "number_of_pages": "Not applicable",
                        "page_size": "Not applicable",
                        "dimensions": "Not applicable",
                        "duration": "Not applicable",
                        "number_of_slides": "Not applicable",
                        "number_of_paragraphs": "Not applicable",
                    },
                ],
                "web_download_url": [
                    {
                        "URL": "https://s3.amazonaws.com/bucket-name/random-file-1.mp3",
                        "file_size": "Unknown",
                        "file_type": "mp3",
                        "number_of_pages": "Not applicable",
                        "page_size": "Not applicable",
                        "dimensions": "Not applicable",
                        "duration": "Not applicable",
                        "number_of_slides": "Not applicable",
                        "number_of_paragraphs": "Not applicable",
                    },
                    {
                        "URL": "https://s3.amazonaws.com/bucket-name/random-file-2.mp4",
                        "file_size": "Unknown",
                        "file_type": "mp4",
                        "number_of_pages": "Not applicable",
                        "page_size": "Not applicable",
                        "dimensions": "Not applicable",
                        "duration": "Not applicable",
                        "number_of_slides": "Not applicable",
                        "number_of_paragraphs": "Not applicable",
                    },
                ],
                "print_download_url": [],
                "transcript_url": [
                    {
                        "URL": "https://s3.amazonaws.com/bucket-name/random-transcript-1.pdf",
                        "file_size": "Unknown",
                        "file_type": "pdf",
                        "number_of_pages": "Not applicable",
                        "page_size": "Not applicable",
                        "dimensions": "Not applicable",
                        "duration": "Not applicable",
                        "number_of_slides": "Not applicable",
                        "number_of_paragraphs": "Not applicable",
                    },
                    {
                        "URL": "https://s3.amazonaws.com/bucket-name/random-transcript-2.txt",
                        "file_size": "Unknown",
                        "file_type": "txt",
                        "number_of_pages": "Not applicable",
                        "page_size": "Not applicable",
                        "dimensions": "Not applicable",
                        "duration": "Not applicable",
                        "number_of_slides": "Not applicable",
                        "number_of_paragraphs": "Not applicable",
                    },
                ],
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
            unit_of_measure=15,
            quantity_available=100,
            available_from_choice="specific_date",
            order_from_date="2024-09-01",
            order_end_date="2024-12-31",
            product_type="Leaflets",
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
def order_limits(db, product, organization):
    """Fixture to create sample order limits for multiple products."""

    slug_order_limit_1 = generate_unique_slug(
        f"test-order-limit-1-{str(uuid.uuid4())}", OrderLimitPage
    )
    slug_order_limit_2 = generate_unique_slug(
        f"test-order-limit-2-{str(uuid.uuid4())}", OrderLimitPage
    )

    order_limits = []

    # Create or get parent page for order limits
    order_limits_page = get_or_create_parent_page("Order Limits", "order-limits")

    # Create or get Order Limit for product 1
    order_limit_id_1 = "1"
    if not OrderLimitPage.objects.filter(order_limit_id=order_limit_id_1).exists():
        order_limit_instance_1 = OrderLimitPage(
            title="Order Limit Title 1",
            slug=slugify(slug_order_limit_1),
            order_limit_id=order_limit_id_1,
            order_limit=10,  # Example limit for product 1
            product_ref=product[0],
            organization_ref=organization,
        )
        order_limits_page.add_child(instance=order_limit_instance_1)
        order_limit_instance_1.save()
        order_limits.append(order_limit_instance_1)  # Add to the list
    else:
        order_limit_instance_1 = OrderLimitPage.objects.get(
            order_limit_id=order_limit_id_1
        )
        order_limits.append(order_limit_instance_1)  # Add existing instance to the list

    # Create or get Order Limit for product 2
    order_limit_id_2 = "2"
    if not OrderLimitPage.objects.filter(order_limit_id=order_limit_id_2).exists():
        order_limit_instance_2 = OrderLimitPage(
            title="Order Limit Title 2",
            slug=slugify(slug_order_limit_2),
            order_limit_id=order_limit_id_2,
            order_limit=10,  # Example limit for product 2
            product_ref=product[1],
            organization_ref=organization,
        )
        order_limits_page.add_child(instance=order_limit_instance_2)
        order_limit_instance_2.save()
        order_limits.append(order_limit_instance_2)  # Add to the list
    else:
        order_limit_instance_2 = OrderLimitPage.objects.get(
            order_limit_id=order_limit_id_2
        )
        order_limits.append(order_limit_instance_2)  # Add existing instance to the list

    return order_limits  # Return the list of order limit instances


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
class TestOrderLimitPageViewSet:
    def test_create_order_limit_success(self, auth_api_client, order_limits, db):
        """Positive test: Create order limit with valid product and organization."""
        product = order_limits[0].product_ref  # Assuming this is a valid product
        organization = order_limits[
            0
        ].organization_ref  # Assuming this is a valid organization

        url = reverse(
            "orderlimitpage-list"
        )  # Adjust the URL name as per your configuration
        data = {
            "title": "New Order Limit",
            "order_limit_id": "15",
            "product_ref": product.product_id,
            "organization_ref": organization.organization_id,
            "order_limit": 15,
        }

        response = auth_api_client.post(url, data=data, format="json")
        # logging.info('RES:', response.json())
        assert response.status_code == status.HTTP_201_CREATED
        assert response.data["created_order_limits"][0]["order_limit_id"] == "15"

    def test_create_order_limit_invalid_product(
        self, auth_api_client, order_limits, db
    ):
        """Negative test: Attempt to create order limit with a non-existent product."""
        organization = order_limits[0].organization_ref  # Valid organization
        invalid_product_id = "invalid-product-id"  # Non-existent product_id

        url = reverse("orderlimitpage-list")
        data = {
            "title": "Invalid Product Test",
            "product_ref": invalid_product_id,
            "organization_ref": organization.organization_id,
            "order_limit": 10,
        }

        response = auth_api_client.post(url, data=data, format="json")
        # logging.info('RES:', response.json())
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["errors"][0]["error"] == "Product does not exist"

    def test_create_order_limit_invalid_organization(
        self, auth_api_client, order_limits, db
    ):
        """Negative test: Attempt to create order limit with a non-existent organization."""
        product = order_limits[0].product_ref  # Valid product
        invalid_organization_id = (
            "invalid-organization-id"  # Non-existent organization_id
        )

        url = reverse("orderlimitpage-list")
        data = {
            "title": "Invalid Organization Test",
            "product_ref": product.product_id,
            "organization_ref": invalid_organization_id,
            "order_limit": 20,
        }

        response = auth_api_client.post(url, data=data, format="json")
        # logging.info('RESPONSE', response.json())
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["errors"][0]["error"] == "Organization does not exist"

    def test_update_order_limit_success(self, auth_api_client, order_limits, db):
        """Positive test: Update an order limit with valid product and organization."""
        order_limit = order_limits[0]
        product = order_limits[1].product_ref  # New valid product
        organization = order_limits[1].organization_ref  # New valid organization

        url = reverse("orderlimitpage-detail", args=[order_limit.order_limit_id])
        data = {
            "product_ref": product.product_id,
            "organization_ref": organization.organization_id,
            "order_limit": 25,
        }

        response = auth_api_client.put(url, data=data)
        assert response.status_code == status.HTTP_200_OK
        assert response.data["order_limit"] == 25

    def test_update_order_limit_invalid_product(
        self, auth_api_client, order_limits, db
    ):
        """Negative test: Attempt to update an order limit with a non-existent product."""
        order_limit = order_limits[0]
        invalid_product_id = "invalid-product-id"  # Non-existent product_id

        url = reverse("orderlimitpage-detail", args=[order_limit.order_limit_id])
        data = {
            "product_ref": invalid_product_id,
            "organization_ref": order_limit.organization_ref.organization_id,
            "order_limit": 30,
        }

        response = auth_api_client.put(url, data=data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "Product does not exist"

    def test_update_order_limit_invalid_organization(
        self, auth_api_client, order_limits, db
    ):
        """Negative test: Attempt to update an order limit with a non-existent organization."""
        order_limit = order_limits[0]
        invalid_organization_id = (
            "invalid-organization-id"  # Non-existent organization_id
        )

        url = reverse("orderlimitpage-detail", args=[order_limit.order_limit_id])
        data = {
            "product_ref": order_limit.product_ref.product_id,
            "organization_ref": invalid_organization_id,
            "order_limit": 40,
        }

        response = auth_api_client.put(url, data=data)
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.data["error"] == "Organization does not exist"


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        OrderLimitPage.objects.all().delete()
        Program.objects.all().delete()
        Organization.objects.all().delete()
        ProductUpdate.objects.all().delete()
        Product.objects.all().delete()
        ProductUpdate.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Page.objects.all().delete()
        logger.info("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)


#
