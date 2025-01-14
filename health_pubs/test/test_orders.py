import logging
import uuid
from io import BytesIO

import jwt
import pandas as pd
import pytest
from core.addresses.models import Address
from core.establishments.models import Establishment
from core.languages.models import LanguagePage
from core.order_limits.models import OrderLimitPage
from core.orders.models import Order, OrderItem
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
def address(db, user):
    """Fixture to create a sample address."""
    slug_address = generate_unique_slug(
        f"test-address-{str(uuid.uuid4())}-{str(timezone.now())}", Address
    )

    # Create or get parent page for addresses
    addresses_page = get_or_create_parent_page("Addresses", "addresses")

    # Create or get Address
    if not Address.objects.filter(address_id="1").exists():
        address_instance = Address(
            title="Test Address",
            slug=slugify(slug_address),
            address_id="1",
            address_line1="123 Test St",
            city="Test City",
            country="Test Country",
            is_default=True,
            verified=True,
            user_ref=user,
        )
        addresses_page.add_child(instance=address_instance)
        address_instance.save()
    else:
        address_instance = Address.objects.get(address_id="1")

    return address_instance


@pytest.fixture
def order(db, user, address):
    """Fixture to create a sample order."""
    slug_order = generate_unique_slug(
        f"test-order-{str(uuid.uuid4())}-{str(timezone.now())}", Order
    )

    # Create or get parent page for orders
    orders_page = get_or_create_parent_page("Orders", "orders")

    # Create or get Order
    if not Order.objects.filter(order_id="1").exists():
        order_instance = Order(
            title="Test Order",
            slug=slugify(slug_order),
            order_id="1",
            user_ref=user,
            order_confirmation_number="CONF123456",
            tracking_number="TRACK123",
            address_ref=address,
            order_origin="by_user",
        )
        orders_page.add_child(instance=order_instance)
        order_instance.save()
    else:
        order_instance = Order.objects.get(order_id="1")

    return order_instance


@pytest.fixture
def order_item(db, order, product):
    """Fixture to create a sample order item."""
    slug_order_item = generate_unique_slug(
        f"test-order-item-{str(uuid.uuid4())}-{str(timezone.now())}", OrderItem
    )

    # Create or get parent page for order items
    order_items_page = get_or_create_parent_page("Order Items", "order-items")

    # Create or get OrderItem
    if not OrderItem.objects.filter(order_item_id="1").exists():
        order_item_instance = OrderItem(
            title="Test Order Item",
            slug=slugify(slug_order_item),
            order_item_id=str(uuid.uuid4()),
            order_ref=order,
            product_ref=product,
            quantity=2,
            status="Confirmed",
        )
        order_items_page.add_child(instance=order_item_instance)
        order_item_instance.save()
    else:
        order_item_instance = OrderItem.objects.get(order_item_id="1")

    return order_item_instance


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
            status="live",
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

    # Create or get Establishment 1
    if not Establishment.objects.filter(establishment_id="131").exists():
        establishment_1 = Establishment(
            establishment_id="131",
            title="Test Establishment 1",
            slug=slugify(slug_establishment_1),
            organization_ref=organization,
            name="Test Establishment 1",
            full_external_key="PR|TP",
        )
        establishments_page.add_child(instance=establishment_1)
        establishment_1.save()
    else:
        establishment_1 = Establishment.objects.get(establishment_id="131")

    # Create or get Establishment 2
    if not Establishment.objects.filter(establishment_id="132").exists():
        establishment_2 = Establishment(
            establishment_id="132",
            title="Test Establishment 2",
            slug=slugify(slug_establishment_2),
            organization_ref=organization,
            name="Test Establishment 2",
            full_external_key="PR|GD",
        )
        establishments_page.add_child(instance=establishment_2)
        establishment_2.save()
    else:
        establishment_2 = Establishment.objects.get(establishment_id="132")

    return [establishment_1, establishment_2]


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


@pytest.fixture
def mock_data(product, address):
    return {
        "order_items": [
            {"product_code": product[0].product_code, "quantity": 2},
            {"product_code": product[1].product_code, "quantity": 1},
        ],
        "user_info": {
            "first_name": "John",
            "last_name": "Doe",
            "email": "john.doe@example.com",
            "mobile_number": "1234567890",
        },
        "address_ref": address.address_id,
        "tracking_number": "TRACK12345",
    }


@pytest.fixture
def orders_excel_file(user):
    """Fixture to create a mock orders Excel file."""
    data = {
        "order_id": [1, 2],
        "order_date": ["01/01/2023 10:00", "02/01/2023 11:00"],
        "user_id": [user.user_id, user.user_id],
        "order_origin": ["by_user", "order_on_behalf"],
        "shipping_address_line_1": ["123 Main St", "456 Another St"],
        "shipping_address_line_2": ["Apt 1", "Apt 2"],
        "shipping_address_city": ["CityA", "CityB"],
        "shipping_address_postcode": ["12345", "54321"],
        "shipping_address_country": ["CountryA", "CountryB"],
        "shipping_address_county": ["CountyA", "CountyB"],
    }
    df = pd.DataFrame(data)
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    return buffer


@pytest.fixture
def order_items_excel_file():
    """Fixture to create a mock order items Excel file."""
    data = {
        "order_item_id": [1, 2],
        "order_id": [1, 2],
        "ProductCode": ["prod-1", "prod-2"],
        "order_line_quantity": [25, 3],
        "quantity_inprogress": [10, 0],
        "quantity_shipped": [10, 3],
        "quantity_cancelled": [5, 0],
    }
    df = pd.DataFrame(data)
    buffer = BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)  # Go to the start of the BytesIO buffer
    return buffer


# @pytest.mark.django_db
# class TestMigrateOrdersAPIView:


#     def test_migrate_orders_success(
#         self, auth_api_client_user, orders_excel_file, order_items_excel_file
#     ):
#         """Positive test for migrating orders and order items."""
#         url = reverse("migrate_orders")
#         response = auth_api_client_user.post(
#             url,
#             data={
#                 "orders_excel": orders_excel_file,
#                 "order_items_excel": order_items_excel_file,
#             },
#         )

#         logging.info("Response:", response.json())
#         assert response.status_code == status.HTTP_200_OK
#         assert response.json()["message"] == "Migration completed successfully."

#     def test_migrate_orders_missing_files(self, auth_api_client_user):
#         """Negative test for migrating orders when files are missing."""
#         url = reverse("migrate_orders")
#         response = auth_api_client_user.post(url, data={})
#         logging.info("Res", response.json())

#         assert response.status_code == status.HTTP_400_BAD_REQUEST
#         assert (
#             response.json()["error"]
#             == "Both orders and order items files are required."
#         )

#     def test_migrate_orders_missing_required_fields(
#         self, auth_api_client_user, order_items_excel_file
#     ):
#         """Negative test for migrating orders when required fields are missing in orders file."""

#         # Create an orders Excel file missing the 'order_date' field
#         data = {
#             "oder_id": ["334"],  # Missing 'order_date'
#             "user_id": ["user-1"],
#             "order_origin": ["by_user"],
#             "shipping_address_line_1": ["123 Main St"],
#             "shipping_address_line_2": ["Apt 1"],
#             "shipping_address_city": ["CityA"],
#             "shipping_address_postcode": ["12345"],
#             "shipping_address_country": ["CountryA"],
#             "shipping_address_county": ["CountyA"],
#         }
#         orders_df = pd.DataFrame(data)
#         orders_buffer = BytesIO()
#         orders_df.to_excel(orders_buffer, index=False)
#         orders_buffer.seek(0)

#         url = reverse("migrate_orders")
#         response = auth_api_client_user.post(
#             url,
#             data={
#                 "orders_excel": orders_buffer,
#                 "order_items_excel": order_items_excel_file,
#             },
#         )

#         logging.info("RESPONSE:", response.json())
#         assert response.status_code == status.HTTP_400_BAD_REQUEST
#         assert (
#             response.json()["error"]
#             == "Missing required field in orders file: order_date"
#         )


# @pytest.mark.django_db
# class TestDeleteMigratedOrdersAPIView:
#     def test_delete_orders_success(self, auth_api_client_user, order):
#         """Positive test for deleting all orders and order items."""
#         url = reverse("delete_all")
#         response = auth_api_client_user.delete(url)

#         assert response.status_code == status.HTTP_200_OK
#         assert "Successfully deleted" in response.data["message"]


@pytest.mark.django_db
class TestOrderViewSet:
    # Positive test case for admin order creation
    def test_create_order_for_admin_success(
        self, user_admin, auth_api_client_admin, mock_data
    ):

        url = reverse("order-create-for-admin")
        print("User Ref", user_admin.user_id)

        payload = {
            "order_id": "12345",
            "order_items": mock_data["order_items"],
            "user_info": mock_data["user_info"],
            "user_ref": user_admin.user_id,
            "address_ref": mock_data["address_ref"],
            "order_confirmation_number": "CONFIRM123",
            "order_origin": "order_on_behalf",
        }

        response = auth_api_client_admin.post(url, payload, format="json")

        # Log response data for debugging
        logging.info(f"Response Data: {response.json()}")

        assert response.status_code == status.HTTP_201_CREATED
        assert "order_id" in response.data
        assert response.data["order_id"] == payload["order_id"]

    # # Negative test case for admin order creation with missing user data
    # def test_create_order_for_admin_missing_user(
    #     self, admin_user, auth_api_client_admin, mock_data
    # ):

    #     url = reverse("order-create-for-admin")

    #     payload = {
    #         "order_id": "12345",
    #         "order_items": mock_data["order_items"],
    #         "address_ref": mock_data["address_ref"],
    #         "tracking_number": "TRACK12345",
    #     }

    #     response = auth_api_client_admin.post(url, payload, format="json")

    #     # Log response data for debugging
    #     logging.info(f"Response Data: {response.json()}")

    #     assert response.status_code == status.HTTP_400_BAD_REQUEST
    #     response_data = response.json()
    #     assert response_data["error_code"] == "USER_REF_REQUIRED"
    #     assert (
    #         response_data["error_message"]
    #         == "The logged-in user's reference is required."
    #     )

    # # Negative test case for admin order creation with invalid address reference
    # def test_create_order_for_admin_invalid_address(
    #     self, user_admin, admin_user, auth_api_client_admin, mock_data
    # ):

    #     url = reverse("order-create-for-admin")

    #     payload = {
    #         "order_id": "12345",
    #         "order_items": mock_data["order_items"],
    #         "user_ref": user_admin.user_id,
    #         "user_info": mock_data["user_info"],
    #         "address_ref": "invalid_address_id",
    #         "tracking_number": "TRACK12345",
    #     }

    #     response = auth_api_client_admin.post(url, payload, format="json")

    #     assert response.status_code == status.HTTP_400_BAD_REQUEST
    #     response_data = response.json()
    #     assert response_data["error_code"] == "ADDRESS_NOT_FOUND"
    #     assert response_data["error_message"] == "Address not found."

    # # Positive test case for regular user order creation
    # def test_create_order_success(self, user, auth_api_client_user, mock_data):

    #     url = reverse("order-list")

    #     payload = {
    #         "order_id": "12345",
    #         "order_items": mock_data["order_items"],
    #         "user_ref": user.user_id,
    #         "address_ref": mock_data["address_ref"],
    #         "tracking_number": "TRACK12345",
    #         "order_confirmation_number": "CONFM123334",
    #         "order_origin": "by_user",
    #     }

    #     response = auth_api_client_user.post(url, payload, format="json")

    #     logging.info(f"Response Data: {response.json()}")

    #     assert response.status_code == status.HTTP_201_CREATED
    #     assert "order_id" in response.data
    #     assert response.data["order_id"] == payload["order_id"]

    # # Negative test case for regular user order creation exceeding product limit
    # def test_create_order_exceeds_limit(
    #     self, order_limits, user, auth_api_client_user, mock_data
    # ):
    #     url = reverse("order-list")

    #     # Set the order limits for each product
    #     # Assuming each order limit is set to 10, and we'll create an order that exceeds this limit
    #     payload = {
    #         "order_id": "12345",
    #         "order_items": [
    #             {
    #                 "product_code": order_limits[0].product_ref.product_code,
    #                 "quantity": 15,
    #             },  # Exceeds limit for product 1
    #             {
    #                 "product_code": order_limits[1].product_ref.product_code,
    #                 "quantity": 5,
    #             },  # Within limit for product 2
    #         ],
    #         "user_ref": user.user_id,
    #         "address_ref": mock_data["address_ref"],
    #         "order_confirmation_number": "CONFM123334",
    #         "order_origin": "by_user",
    #     }

    #     response = auth_api_client_user.post(url, payload, format="json")
    #     logging.info(response.json())

    #     assert response.status_code == status.HTTP_400_BAD_REQUEST
    #     assert "error_code" in response.json()
    #     assert (
    #         response.json()["error_message"] == "Order limit exceeded for this product."
    #     )

    # # Negative test case for regular user order creation with invalid product code
    # def test_create_order_invalid_product(self, user, auth_api_client_user, mock_data):
    #     url = reverse("order-list")

    #     payload = {
    #         "order_id": "12345",
    #         "order_items": [{"product_code": "INVALID_CODE", "quantity": 2}],
    #         "user_ref": user.user_id,
    #         "address_ref": mock_data["address_ref"],
    #         "tracking_number": "TRACK12345",
    #         "order_confirmation_number": "CONFM123334",
    #         "order_origin": "by_user",
    #     }

    #     response = auth_api_client_user.post(url, payload, format="json")
    #     logging.info(response.json())

    #     assert response.status_code == status.HTTP_400_BAD_REQUEST
    #     assert response.json()["error_code"] == "PRODUCT_NOT_LIVE"
    #     assert (
    #         response.json()["error_message"]
    #         == "Product with code INVALID_CODE is not live yet."
    #     )

    # def test_list_orders_for_existing_user(self, user, auth_api_client_user, order):
    #     """Positive test for listing orders for a specific user."""

    #     # Using a query parameter for user_id
    #     url = reverse("order-list") + "?user_id=" + str(user.user_id)
    #     response = auth_api_client_user.get(url)

    #     assert response.status_code == status.HTTP_200_OK
    #     assert len(response.data) > 0

    # def test_list_orders_for_non_existent_user(self, auth_api_client_user):
    #     """Negative test for listing orders for a non-existent user."""
    #     url = reverse("order-list") + "?user_id=non-existent-user"
    #     response = auth_api_client_user.get(url)

    #     assert response.status_code == status.HTTP_200_OK
    #     assert response.data == []

    # def test_get_all_orders_when_orders_exist(self, user, auth_api_client_user, order):
    #     """Positive test for getting all orders."""

    #     url = reverse("order-get-all-orders")
    #     response = auth_api_client_user.get(url)

    #     assert response.status_code == status.HTTP_200_OK
    #     assert len(response.data) > 0

    # def test_get_all_orders_when_no_orders_exist(self, auth_api_client_user):
    #     """Negative test for getting all orders when there are none."""
    #     # Optionally, you can clean up the database here to ensure no orders exist
    #     url = reverse("order-get-all-orders")
    #     response = auth_api_client_user.get(url)

    #     assert response.status_code == status.HTTP_200_OK
    #     assert response.data == []  # Expecting an empty list

    # def test_update_non_existent_order(self, user, auth_api_client_user):
    #     """Negative test for updating a non-existent order."""

    #     url = reverse("order-detail", kwargs={"pk": "non-existent-id"})
    #     payload = {"order_origin": "by_user"}

    #     response = auth_api_client_user.put(url, payload, format="json")

    #     assert response.status_code == status.HTTP_404_NOT_FOUND
    #     assert response.data["detail"] == "Order not found."

    # def test_destroy_order_successfully(self, user, auth_api_client_user, order):
    #     """Positive test for deleting an order."""

    #     url = reverse("order-detail", kwargs={"pk": order.order_id})
    #     response = auth_api_client_user.delete(url)

    #     assert response.status_code == status.HTTP_204_NO_CONTENT
    #     assert not Order.objects.filter(order_id=order.order_id).exists()

    # def test_destroy_non_existent_order(self, user, auth_api_client_user):
    #     """Negative test for deleting a non-existent order."""

    #     url = reverse("order-detail", kwargs={"pk": "non-existent-id"})
    #     response = auth_api_client_user.delete(url)

    #     assert response.status_code == status.HTTP_404_NOT_FOUND
    #     assert response.data["detail"] == "No Order matches the given query."


@pytest.fixture(scope="function", autouse=True)
def teardown_db_after_tests(request, db):
    """Teardown fixture to clean up the database after all tests have been carried out."""

    def teardown():
        OrderLimitPage.objects.all().delete()
        Order.objects.all().delete()
        OrderItem.objects.all().delete()
        User.objects.all().delete()
        Role.objects.all().delete()
        Product.objects.all().delete()
        ProductUpdate.objects.all().delete()
        Program.objects.all().delete()
        Address.objects.all().delete()
        Page.objects.all().delete()
        print("Database has been cleaned up after all tests.")

    request.addfinalizer(teardown)
