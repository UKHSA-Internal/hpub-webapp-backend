import logging
import traceback
import uuid
from datetime import datetime
from uuid import uuid4
from django.db import transaction
import pandas as pd
from core.addresses.models import Address
from core.addresses.serializers import AddressSerializer
from core.errors.enums import ErrorCode, ErrorMessage
from core.errors.error_function import handle_error
from core.establishments.models import Establishment
from core.order_limits.models import OrderLimitPage
from core.products.models import Product
from core.roles.models import Role
from core.users.models import User
from core.users.permissions import IsAdminOrRegisteredUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from core.utils.order_confirmation_generation import generate_order_confirmation
from core.utils.send_order_confirmation import send_notification
from django.contrib.contenttypes.models import ContentType
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.models import Page
from rest_framework.exceptions import NotFound
import time
from psycopg2 import errors
from django.db import transaction, IntegrityError
from core.event_analytics.models import EventAnalytics
from core.utils.confirmation_generator import generate_confirmation_number

from .models import Order, OrderItem
from .serializers import OrderItemSerializer, OrderSerializer

logger = logging.getLogger(__name__)


from django.db import transaction


class OrderViewSet(viewsets.ModelViewSet):

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrRegisteredUser]
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

    @action(detail=False, methods=["post"], url_path="admin")
    def create_for_admin(self, request, *args, **kwargs):
        data = request.data.copy()
        items_data = data.pop("order_items", [])
        address_ref = data.pop("address_ref", None)
        user_data = data.pop("user_info", None)
        user_id = data.pop("user_ref", None)

        # --- pre-checks ---
        if not user_id:
            return handle_error(
                ErrorCode.USER_REF_REQUIRED,
                ErrorMessage.USER_REF_REQUIRED,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        if not user_data:
            return handle_error(
                ErrorCode.USER_INFO_REQUIRED,
                ErrorMessage.USER_INFO_REQUIRED,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        try:
            parent_page = self._get_or_create_parent_page()
        except Exception:
            return handle_error(
                ErrorCode.PAGE_CREATION_ERROR,
                ErrorMessage.PAGE_CREATION_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        try:
            delivery_user = self._get_or_create_user(user_data, parent_page)
            delivery_user.refresh_from_db()
            admin_user = self._get_existing_user(user_id)

            if (
                not admin_user.establishment_ref
                or not admin_user.establishment_ref.full_external_key
            ):
                return JsonResponse(
                    {
                        "error": "User's establishment_ref or full_external_key is missing."
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            data["full_external_key"] = admin_user.establishment_ref.full_external_key

            if not self._validate_order_limits(items_data, admin_user):
                return handle_error(
                    ErrorCode.ORDER_LIMIT_EXCEEDED,
                    ErrorMessage.ORDER_LIMIT_EXCEEDED,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

        except IntegrityError:
            return handle_error(
                ErrorCode.USER_CREATION_ERROR,
                ErrorMessage.USER_CREATION_ERROR,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        except Exception:
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        if address_ref:
            try:
                address_instance = Address.objects.get(address_id=address_ref)
            except Address.DoesNotExist:
                return handle_error(
                    ErrorCode.ADDRESS_NOT_FOUND,
                    ErrorMessage.ADDRESS_NOT_FOUND,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
        else:
            address_instance = None

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    order = self._create_order_instance(
                        data, delivery_user, address_instance, parent_page
                    )
                    self._create_order_items(
                        items_data, order, parent_page, delivery_user
                    )
                    self._update_product_quantities(items_data)

                    # send confirmation email, but don’t abort on failure
                    try:
                        send_notification(order)
                    except Exception as e:
                        logger.warning(f"Email failed for {order.order_id}: {e}")

                    # record analytics under its own parent page
                    try:
                        self.record_reorder_events(order, request)
                    except Exception as e:
                        logger.error(f"Analytics failed for {order.order_id}: {e}")

                    serializer = self.get_serializer(order)
                    return Response(serializer.data, status=status.HTTP_201_CREATED)

            except IntegrityError as exc:
                if self._is_path_collision(exc) and attempt < max_retries - 1:
                    time.sleep(0.1 * (2**attempt))
                    continue
                return handle_error(
                    ErrorCode.ORDER_CREATION_ERROR,
                    ErrorMessage.ORDER_CREATION_ERROR,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        items_data = data.pop("order_items", [])
        address_ref = data.pop("address_ref", None)
        user_ref = data.pop("user_ref", None)

        # --- pre-checks ---
        for item in items_data:
            if not self._is_product_live(item.get("product_code")):
                return JsonResponse(
                    {
                        "error_code": ErrorCode.PRODUCT_NOT_LIVE.value,
                        "error_message": ErrorMessage.product_not_live(
                            item.get("product_code")
                        ),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        parent_page = self._get_or_create_parent_page_or_error()
        user = self._get_user_or_error(user_ref)
        data["user_ref"] = user

        if not user.establishment_ref:
            return JsonResponse(
                {"error": "User's establishment_ref is missing."},
                status=status.HTTP_404_NOT_FOUND,
            )
        data["full_external_key"] = user.establishment_ref.full_external_key

        if not self._validate_order_limits(items_data, user):
            return handle_error(
                ErrorCode.ORDER_LIMIT_EXCEEDED,
                ErrorMessage.ORDER_LIMIT_EXCEEDED,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        if address_ref:
            try:
                address_instance = Address.objects.get(address_id=address_ref)
            except Address.DoesNotExist:
                raise ValidationError({"address_ref": ErrorMessage.ADDRESS_NOT_FOUND})
        else:
            address_instance = None

        max_retries = 3
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    order = self._create_order_instance(
                        data, user, address_instance, parent_page
                    )
                    self._create_order_items(items_data, order, parent_page, user)
                    self._update_product_quantities(items_data)

                    try:
                        send_notification(order)
                    except Exception as e:
                        logger.warning(f"Email failed for {order.order_id}: {e}")

                    try:
                        self.record_reorder_events(order, request)
                    except Exception as e:
                        logger.error(f"Analytics failed for {order.order_id}: {e}")

                    serializer = self.get_serializer(order)
                    return Response(serializer.data, status=status.HTTP_201_CREATED)

            except IntegrityError as exc:
                if self._is_path_collision(exc) and attempt < max_retries - 1:
                    time.sleep(0.1 * (2**attempt))
                    continue
                raise ValidationError({"detail": ErrorMessage.ORDER_CREATION_ERROR})

    # Helper methods

    def _is_path_collision(self, err: IntegrityError) -> bool:
        """
        True if the IntegrityError was a UNIQUE violation on wagtailcore_page.path.
        """
        cause = getattr(err, "__cause__", None)
        return (
            isinstance(cause, errors.UniqueViolation)
            and getattr(cause.diag, "constraint_name", "")
            == "wagtailcore_page_path_key"
        )

    def call_record_reorder_events(self, order_instance, request):
        # Now, record reorder events (if any) for this order.
        try:
            self.record_reorder_events(order_instance, request)
        except Exception as e:
            logger.exception(
                f"Failed to record reorder events for order {order_instance.order_id}: {e}"
            )

    def record_reorder_events(self, order_instance, request):
        # ensure an analytics parent exists
        parent, _ = Page.objects.get_or_create(
            slug="event-analytics",
            defaults={"title": "Event analytics", "content_type": Page.content_type},
        )
        session_id = request.headers.get("X-Session-ID", "unknown")
        user = order_instance.user_ref

        for item in order_instance.order_items.all():
            product = item.product_ref
            if (
                not Order.objects.filter(
                    user_ref=user, order_items__product_ref=product
                )
                .exclude(order_id=order_instance.order_id)
                .exists()
            ):
                continue

            event = EventAnalytics(
                event_type="reorder",
                user_ref=user,
                session_id=session_id,
                metadata={
                    "order_id": order_instance.order_id,
                    "product_code": product.product_code,
                    "quantity": item.quantity,
                    "timestamp": datetime.now().isoformat(),
                },
            )
            parent.add_child(instance=event)

    def _is_product_live(self, product_code):
        try:
            product = Product.objects.get(product_code=product_code)
            return product.status == "live"
        except Product.DoesNotExist:
            logger.warning(f"Product with code {product_code} does not exist.")
            return False
        except Exception as e:
            logger.exception(
                f"Unexpected error occurred while checking if product is live: {e}",
                extra={
                    "product_code": product_code,
                    "traceback": traceback.format_exc(),
                },
            )
            raise APIException(ErrorMessage.INTERNAL_SERVER_ERROR)

    def _validate_order_limits(self, items_data, user_instance):
        # Accumulate quantities by product code
        product_quantities = {}
        for item in items_data:
            product_code = item["product_code"]
            quantity = item["quantity"]
            product_quantities[product_code] = (
                product_quantities.get(product_code, 0) + quantity
            )

        # Check each product's order limit
        for product_code, total_quantity in product_quantities.items():
            try:
                product = Product.objects.get(product_code=product_code)
            except Product.DoesNotExist:
                logger.error(f"Product not found: Code {product_code}")
                raise ValidationError(
                    {
                        "product_code": f"Product with code {product_code} does not exist."
                    }
                )
            except Exception as e:
                logger.exception(
                    f"Unexpected error while retrieving product {product_code}: {e}",
                    extra={
                        "product_code": product_code,
                        "traceback": traceback.format_exc(),
                    },
                )
                raise APIException(ErrorMessage.INTERNAL_SERVER_ERROR)

            order_limit_page = OrderLimitPage.objects.filter(
                organization_ref=user_instance.organization_ref.organization_id,
                product_ref=product,
            ).first()

            if order_limit_page:
                order_limit = order_limit_page.order_limit
                current_total_quantity = (
                    Order.objects.filter(
                        user_ref__organization_ref__organization_id=user_instance.organization_ref.organization_id,
                        order_items__product_ref=product,
                    ).aggregate(total=Sum("order_items__quantity"))["total"]
                    or 0
                )

                if current_total_quantity + total_quantity > order_limit:
                    logger.warning(
                        f"Order limit exceeded for product {product_code}. "
                        f"Order limit: {order_limit}, Current total: {current_total_quantity}, Requested: {total_quantity}"
                    )
                    raise ValidationError(
                        {
                            "error_message": "Order limit exceeded for this product.",
                            "error_code": "ORDER_LIMIT_EXCEEDED",
                            "order_limit": order_limit,
                            "current_total_quantity": current_total_quantity,
                            "requested_quantity": total_quantity,
                        }
                    )

        return True

    def _update_product_quantities(self, items_data):
        print("PRODUCT_Quantity_Items", items_data)
        for item in items_data:
            product = item.get("product_ref")
            print("PRODUCT_REF", product)
            if product is None:
                logger.error("Product reference is None.")
                continue

            product_code = product.product_code
            quantity_ordered = item.get("quantity")

            try:
                if product.update_ref:
                    current_quantity_available = product.update_ref.quantity_available
                    new_quantity_available = (
                        current_quantity_available - quantity_ordered
                    )

                    product.update_ref.quantity_available = new_quantity_available
                    product.update_ref.save()

                    logger.info(
                        f"Updated quantity_available for product_code {product_code}: {new_quantity_available}"
                    )
                else:
                    logger.error(
                        f"No update_ref found for product_code: {product_code}"
                    )

            except Product.DoesNotExist:
                logger.error(f"Product not found for product_code: {product_code}")
            except Exception as e:
                logger.exception(
                    f"Unexpected error while updating quantities for product {product_code}: {e}",
                    extra={
                        "product_code": product_code,
                        "traceback": traceback.format_exc(),
                    },
                )
                raise APIException(ErrorMessage.INTERNAL_SERVER_ERROR)

    def _get_or_create_user(self, user_data, parent_page):
        # 1) Look up any existing user by email…
        user = User.objects.filter(email=user_data["email"]).first()
        role = Role.objects.filter(name="User").first()
        if not role:
            raise NotFound(detail="Role ‘User’ not found.")

        if user:
            # 2) If they exist but have no user_id, give them one—but first
            #    patch any Orders that point at the old blank ID
            if not user.user_id:
                new_uuid = str(uuid4())
                with transaction.atomic():
                    # move all orders with user_ref_id='' → new_uuid
                    Order.objects.filter(user_ref_id="").update(user_ref_id=new_uuid)
                    # now that no child rows point at the old key, update the User
                    User.objects.filter(pk=user.pk).update(user_id=new_uuid)
                # refresh the Python object
                user.user_id = new_uuid
            return user

        # 3) Otherwise create a brand‑new delivery user as before
        unique_slug = self.get_unique_slug(
            slugify(f"user-{user_data.get('email','default')}" + str(datetime.now()))
        )
        user = User(
            user_id=str(uuid4()),
            first_name=user_data["first_name"],
            last_name=user_data["last_name"],
            role_ref=role,
            email=user_data["email"],
            mobile_number=user_data["mobile_number"],
            slug=unique_slug,
            title="user_info_title",
        )
        parent_page.add_child(instance=user)
        user.save()
        return user

    def _get_existing_user(self, user_ref_id):
        """
        Retrieves an existing user by ID.
        """
        return User.objects.get(user_id=user_ref_id)

    def _create_address(self, address_data, user_instance, parent_page):
        """
        Creates and returns a new address instance.
        """
        address_serializer = AddressSerializer(data=address_data)
        address_serializer.is_valid(raise_exception=True)

        address_instance = Address(
            address_line1=address_data.get("address_line1"),
            address_line2=address_data.get("address_line2", ""),
            address_line3=address_data.get("address_line3", ""),
            city=address_data.get("city"),
            county=address_data.get("county", ""),
            postcode=address_data.get("postcode"),
            country=address_data.get("country"),
            is_default=address_data.get("is_default", False),
            verified=address_data.get("verified", False),
            user_ref=user_instance,
            slug=self.get_unique_slug(
                slugify(
                    f"address-{address_data.get('postcode', 'default')}"
                    + str(datetime.now())
                )
            ),
            title=address_data.get("address_line1", "Address Title"),
        )
        parent_page.add_child(instance=address_instance)
        address_instance.save()
        address_instance.refresh_from_db()
        logger.info(f"Address created: ID={address_instance.id}")
        return address_instance

    def _create_order_instance(self, data, user_instance, address_ref, parent_page):
        """
        Creates and returns a new order instance.
        """
        unique_slug = self.get_unique_slug(
            slugify("orders_title" + str(datetime.now()))
        )
        order_id = data.get("order_id")
        if order_id is None:
            order_id = str(uuid.uuid4())

        order_instance = Order(
            title="Order Title",
            slug=unique_slug,
            order_id=order_id,
            user_ref=user_instance,
            address_ref=address_ref,
            order_confirmation_number=generate_confirmation_number(),
            order_origin=data.get("order_origin"),
            full_external_key=data.get("full_external_key"),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )
        parent_page.add_child(instance=order_instance)
        order_instance.save()
        order_instance.refresh_from_db()
        logger.info(f"Order created: ID={order_instance.id}")
        return order_instance

    def _create_order_items(
        self, items_data, order_instance, parent_page, user_instance
    ):
        """
        Creates order items and associates them with the order.
        """
        print("ORDER_ITEM_DATA", items_data)
        for item_data in items_data:
            product_code = item_data.get("product_code")
            print("ProductCode", product_code)
            if product_code:
                try:
                    product_instance = Product.objects.get(product_code=product_code)
                    print(f"Product retrieved: {product_instance}")
                    item_data["product_ref"] = product_instance
                    # del item_data["product_code"]
                except Product.DoesNotExist:
                    logger.warning(f"Product not found: {product_code}")
                    return {"error": f"Product with code {product_code} not found."}
            else:
                item_data["product_ref"] = None

            item_slug = slugify(
                f"{order_instance.slug}-{product_instance.product_code}"
                + str(datetime.now())
            )
            item_title = (
                f"{order_instance.title} - {product_instance.title}"
                if product_code
                else "Unknown Product"
            )
            order_item_instance = OrderItem(
                order_ref=order_instance,
                slug=item_slug,
                title=item_title,
                quantity=item_data.get("quantity"),
                product_ref=item_data.get("product_ref"),
                product_code=product_code,
            )
            parent_page.add_child(instance=order_item_instance)
            order_item_instance.save()
            order_item_instance.refresh_from_db()
            logger.info(f"Order item created: ID={order_item_instance.id}")

    def _send_order_confirmation(self, order_instance):
        """
        Sends order confirmation via GOV.UK Notify API.
        """
        confirmation_message = generate_order_confirmation(
            order_instance
        )  # Generate the confirmation message

        # logging.info("confirmation_message", confirmation_message["items_table"])

        user_instance = order_instance.user_ref  # Get the user instance from the order

        if user_instance and user_instance.email:
            # Send the notification using the generated confirmation_message
            send_notification(
                "email",
                user_instance.email,
                user_instance.first_name,
                confirmation_message["confirmation_number"],
                confirmation_message["confirmation_date"],
                confirmation_message["order_id"],
                confirmation_message["order_status"],
                confirmation_message["items_table"],
                confirmation_message["shipping_address"],
            )

            # logger.info(response, status_code)

    def _get_or_create_parent_page_or_error(self):
        try:
            return self._get_or_create_parent_page()
        except Exception:
            logger.exception("Error creating or retrieving parent page for orders.")
            raise APIException(
                ErrorMessage.PAGE_CREATION_ERROR, ErrorCode.PAGE_CREATION_ERROR
            )

    def _get_user_or_error(self, user_ref):
        if not user_ref:
            logger.warning("User reference not provided.")
            raise ValidationError({"user_ref": ErrorMessage.USER_NOT_PROVIDED})

        try:
            user = User.objects.get(user_id=user_ref)
            # if not user.is_authorized:
            #     logger.warning(f"User with ID {user_ref} is not authorized.")
            #     raise PermissionDenied(ErrorMessage.USER_NOT_AUTHORIZED)
            return user
        except User.DoesNotExist:
            logger.warning(f"No user found with ID {user_ref}")
            raise ValidationError({"user_ref": ErrorMessage.USER_NOT_FOUND})

    def _get_establishment_ref(self, organization_ref):
        return (
            Establishment.objects.filter(organization_ref=organization_ref).first()
            if organization_ref
            else None
        )

    def _create_address_if_needed(self, address_data, user_instance, parent_page):
        if not address_data:
            return None

        address_serializer = AddressSerializer(data=address_data)
        if not address_serializer.is_valid():
            logger.warning(f"Address data is invalid: {address_serializer.errors}")
            raise ValidationError(address_serializer.errors)

        try:
            address_instance = Address(
                **address_data,
                user_ref=user_instance,
                slug=self.get_unique_slug(
                    slugify(
                        f"address-{address_data.get('postcode', 'default')}"
                        + str(datetime.now())
                    )
                ),
                title=address_data.get("address_line1", "Address Title"),
            )
            parent_page.add_child(instance=address_instance)
            address_instance.save()
            return address_instance
        except IntegrityError:
            logger.exception(
                "Integrity error occurred while creating address.",
                extra={
                    "address_data": address_data,
                    "user_id": getattr(user_instance, "id", None),
                    "parent_page_id": getattr(parent_page, "id", None),
                },
            )
            raise ValidationError(ErrorMessage.ADDRESS_CREATION_ERROR)
        except Exception as e:
            logger.exception(
                f"Unexpected error occurred while creating address: {e}",
                extra={
                    "address_data": address_data,
                    "user_id": getattr(user_instance, "id", None),
                    "parent_page_id": getattr(parent_page, "id", None),
                    "traceback": traceback.format_exc(),
                },
            )
            raise APIException(ErrorMessage.INTERNAL_SERVER_ERROR)

    def _get_product_or_none(self, product_code):
        if not product_code:
            return None
        try:
            return Product.objects.get(product_code=product_code)
        except Product.DoesNotExist:
            logger.warning(f"Product with code {product_code} does not exist.")
            raise ValidationError({"product_code": ErrorMessage.PRODUCT_NOT_FOUND})

    def get_unique_slug(self, base_slug):
        queryset = Order.objects.filter(slug__startswith=base_slug)
        if not queryset.exists():
            return base_slug

        num = queryset.count() + 1
        return f"{base_slug}-{num}"

    def _get_or_create_parent_page(self):
        try:
            parent_page = Page.objects.get(slug="orders")
        except Page.DoesNotExist:
            root_page = Page.objects.first()
            parent_page = Page(
                title="Orders",
                slug="orders",
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            root_page.save()
            logger.info("Parent page 'orders' created.")
        return parent_page

    def list(self, request, *args, **kwargs):
        user_id = request.query_params.get("user_id")
        if user_id:
            queryset = self.queryset.filter(user_ref__user_id=user_id)
        else:
            queryset = self.queryset

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"], url_path="get-all-orders")
    def get_all_orders(self, request):
        try:
            # Fetch all orders, you can add filtering or pagination if needed
            orders = Order.objects.all()

            # Serialize the data
            serializer = self.get_serializer(orders, many=True)

            # Return the serialized data
            return Response(serializer.data, status=status.HTTP_200_OK)
        except Exception as e:
            # Handle any unexpected errors
            return Response(
                {"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def update(self, request, *args, **kwargs):
        # Get the order_id from kwargs
        order_id = kwargs.get("pk")

        # Get the order instance using the order_id
        instance = self.get_queryset().filter(order_id=order_id).first()

        if not instance:
            return Response(
                {"detail": "Order not found."}, status=status.HTTP_404_NOT_FOUND
            )

        # Serialize the data
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        logger.warning(f"Update errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        try:
            self.perform_destroy(instance)
            logger.info(f"Order with ID {instance.id} deleted successfully.")
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception:
            logger.exception("Unexpected error occurred while deleting order.")
            return handle_error(
                ErrorCode.ORDER_DELETION_ERROR,
                ErrorMessage.ORDER_DELETION_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def perform_destroy(self, instance):
        instance.delete()


class OrderItemViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrRegisteredUser]
    queryset = OrderItem.objects.all()
    serializer_class = OrderItemSerializer

    def create(self, request, *args, **kwargs):
        logger.info("Starting the creation of a new OrderItem.")

        data = request.data
        logger.info(f"Received data: {data}")

        # Prepare data for OrderItem creation
        slug = slugify("order_item_title")
        unique_slug = self.get_unique_slug(slug)
        data["title"] = "order_item_title"
        data["slug"] = unique_slug
        logger.info(f"Generated slug: {unique_slug}")

        # Fetch or create related `Product` instance

        # Fetch or create related `Product` instance
        product_id = data.get("product_ref")
        if product_id:
            try:
                product_instance = Product.objects.get(id=product_id)
            except Product.DoesNotExist:
                return Response(
                    {"error": f"Product with id {product_id} does not exist"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            data["product_ref"] = product_instance
        else:
            data["product_ref"] = None

        logger.info(f"Product ref after processing: {data['product_ref']}")

        # Find or create the parent page for OrderItems
        try:
            parent_page = Page.objects.get(slug="order-items")
            logger.info(f"Found parent page: {parent_page}")
        except Page.DoesNotExist:
            root_page = (
                Page.objects.first()
            )  # Modify this if your root page is different
            parent_page = Page(
                title="Order Items",
                slug="order-items",
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            parent_page.save()
            logger.info("Parent page 'order-items' created.")

        # Serializer and instance creation
        serializer = self.get_serializer(data=data)
        if serializer.is_valid():
            logger.info("Serializer validated successfully.")
            order_item_instance = OrderItem(
                order_item_id=data.get("order_item_id"),
                title=data["title"],
                slug=data["slug"],
                order_ref=data.get("order_ref"),
                product_ref=data["product_ref"],
                quantity=data.get("quantity"),
            )

            if not parent_page.get_children().exists():
                order_item_instance.depth = parent_page.depth + 1
                order_item_instance.path = parent_page.path + "0001"
                order_item_instance.numchild = 0
                order_item_instance.save()
                parent_page.numchild += 1
                parent_page.save()
                logger.info(
                    f"OrderItem instance created and saved: {order_item_instance}"
                )
            else:
                parent_page.add_child(instance=order_item_instance)
                logger.info(f"OrderItem instance added as child: {order_item_instance}")

            serializer = OrderItemSerializer(order_item_instance)
            logger.info("OrderItem created successfully.")
            logger.info(f"Serialized data: {serializer.data}")
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        else:
            logger.error("Serializer validation failed.")
            logger.info(f"Serializer errors: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get_unique_slug(self, base_slug):
        """Generate a unique slug for the OrderItem."""
        queryset = OrderItem.objects.filter(slug__startswith=base_slug)
        if not queryset.exists():
            return base_slug

        num = queryset.count() + 1
        unique_slug = f"{base_slug}-{num}"
        # logger.info(f"Generated unique slug: {unique_slug}")
        return unique_slug

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance)
        logger.info(f"Retrieved OrderItem instance: {instance}")
        return Response(serializer.data)

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        logger.info("Listed OrderItem instances.")
        return Response(serializer.data)

    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = self.get_serializer(instance, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            logger.info("OrderItem updated successfully.")
            logger.info(f"Updated data: {serializer.data}")
            return Response(serializer.data, status=status.HTTP_200_OK)
        logger.error("Failed to update OrderItem.")
        logger.info(f"Update errors: {serializer.errors}")
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        self.perform_destroy(instance)
        logger.info("OrderItem deleted successfully.")
        return Response(status=status.HTTP_204_NO_CONTENT)

    def perform_destroy(self, instance):
        instance.delete()
        logger.info(f"Destroyed OrderItem instance: {instance}")


class MigrateOrdersAPIView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        logger.info("Starting the order migration process.")

        # Get the files from the request
        orders_file = request.FILES.get("orders_excel")
        order_items_file = request.FILES.get("order_items_excel")

        if not orders_file or not order_items_file:
            logger.error("Both orders and order items files are required.")
            return JsonResponse(
                {"error": "Both orders and order items files are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info("Files received. Processing...")

        # Read the Excel files
        try:
            orders_df = pd.read_excel(orders_file)
            order_items_df = pd.read_excel(order_items_file)
            logger.info("Excel files successfully read.")
        except Exception as e:
            logger.error(f"Error reading Excel files: {str(e)}")
            return JsonResponse(
                {"error": "Failed to read the provided Excel files."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check for required columns in orders
        required_order_fields = ["order_date", "user_id", "order_origin"]
        for field in required_order_fields:
            if field not in orders_df.columns:
                logger.error(f"Missing required field in orders file: {field}")
                return JsonResponse(
                    {"error": f"Missing required field in orders file: {field}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        logger.info("Required columns in orders file are present.")

        # Check for required columns in order items
        required_order_item_fields = ["order_id", "ProductCode", "order_line_quantity"]
        for field in required_order_item_fields:
            if field not in order_items_df.columns:
                logger.error(f"Missing required field in order items file: {field}")
                return JsonResponse(
                    {"error": f"Missing required field in order items file: {field}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        logger.info("Required columns in order items file are present.")

        # Get or create the parent pages for the orders and addresses
        logger.info("Fetching or creating parent pages for orders and addresses.")
        address_parent_page = self.get_or_create_parent_page(
            slug="addresses", title="Addresses"
        )
        order_parent_page = self.get_or_create_parent_page(
            slug="orders", title="Orders"
        )

        # Mapping of original order_id to new order_id
        order_id_mapping = {}

        # Process and create orders
        for _, row in orders_df.iterrows():
            logger.info(f"Processing order {row['order_id']}")
            user_ref = self._get_user_ref(row["user_id"])
            if not user_ref:
                logger.warning(
                    f"Skipping order {row['order_id']} because user_ref does not exist."
                )
                continue  # Skip creating this order

            # Get unique addresses for the order
            address_instances = self._get_or_create_address_ref(
                row, address_parent_page
            )

            for address_instance in address_instances:
                new_order_id = str(uuid.uuid4())  # Generate a unique order ID
                order_data = {
                    "order_id": new_order_id,
                    "order_date": pd.to_datetime(
                        row["order_date"], format="%d/%m/%Y %H:%M"
                    ).to_pydatetime(),
                    "user_ref": user_ref,
                    "order_origin": row["order_origin"],
                    "address_ref": address_instance,
                    "tracking_number": row.get("tracking_number") or None,
                    "order_confirmation_number": generate_confirmation_number(),
                }
                self._create_order_instance(order_data, order_parent_page)

                # Map the original order_id to the new order_id
                order_id_mapping[row["order_id"]] = new_order_id

        logger.info("Orders processing completed.")

        # Process and create order items
        for _, row in order_items_df.iterrows():
            logger.info(f"Processing order item {row['order_item_id']}")

            original_order_id = row["order_id"]
            new_order_id = order_id_mapping.get(original_order_id)

            if new_order_id is None:
                logger.warning(
                    f"Skipping order item {row['order_item_id']} because associated order {original_order_id} was not created."
                )
                continue

            order_ref = self._get_order_ref(new_order_id)
            if not order_ref:
                logger.warning(
                    f"Skipping order item {row['order_item_id']} because order_ref does not exist."
                )
                continue

            # Create order item instance
            order_item_data = {
                # Generate a unique order item ID
                "order_item_id": str(uuid.uuid4()),
                "order_ref": order_ref,
                "product_ref": self._get_product_ref(row["ProductCode"]),
                "quantity": row["order_line_quantity"],
                "quantity_inprogress": row.get("quantity_inprogress", 0),
                "quantity_shipped": row.get("quantity_shipped", 0),
                "quantity_cancelled": row.get("quantity_cancelled", 0),
            }
            self._create_order_item_instance(order_item_data)

        logger.info("Order items processing completed successfully.")
        return JsonResponse(
            {"message": "Migration completed successfully."}, status=status.HTTP_200_OK
        )

    def get_or_create_parent_page(self, slug, title):
        try:
            parent_page = Page.objects.get(slug=slug)
            logger.info(f"Parent page '{title}' found.")
        except Page.DoesNotExist:
            logger.warning(f"Parent page '{title}' not found, creating a new one.")
            try:
                root_page = Page.objects.first()
                parent_page = Page(
                    title=title,
                    slug=slug,
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)
                logger.info(f"Parent page '{title}' created successfully.")
            except Exception as ex:
                logger.error(f"Failed to create parent page '{title}': {str(ex)}")
                raise
        return parent_page

    def _get_user_ref(self, user_id):
        try:
            user_ref = User.objects.get(user_id=user_id)
            logger.info(f"User reference for user_id {user_id} found.")
            return user_ref
        except User.DoesNotExist:
            logger.warning(f"User with user_id {user_id} does not exist.")
            return None

    def _get_or_create_address_ref(self, row, address_parent_page):
        address_data = {
            "address_line1": row["shipping_address_line_1"],
            "address_line2": row.get("shipping_address_line_2", ""),
            "address_line3": row.get("shipping_address_line_3", ""),
            "city": row["shipping_address_city"],
            "postcode": row["shipping_address_postcode"],
            "country": row["shipping_address_country"],
            "county": row["shipping_address_county"],
        }

        address_instances = []
        try:
            # Get all matching addresses
            address_instances = Address.objects.filter(
                address_line1=address_data["address_line1"],
                address_line2=address_data.get("address_line2", ""),
                address_line3=address_data.get("address_line3", ""),
                city=address_data["city"],
                postcode=address_data["postcode"],
                county=address_data["county"],
            ).distinct()

            if address_instances.exists():
                logger.info(f"Found {address_instances.count()} matching addresses.")
            else:
                logger.info(
                    f"Creating a new address for {address_data['address_line1']}, {address_data['city']}."
                )
                user_ref = self._get_user_ref(row.get("user_id"))
                if user_ref is None:
                    logger.warning(
                        f"No user_ref found for user_id: {row.get('user_id')}. Skipping address creation."
                    )
                    return []

                address_instance = Address(
                    title=f"{address_data['address_line1']}, {address_data['city']}",
                    slug=slugify(
                        f"{address_data['city']}-{address_data['postcode']}-{str(uuid.uuid4())}"
                    ),
                    address_line1=address_data["address_line1"],
                    address_line2=address_data.get("address_line2", ""),
                    address_line3=address_data.get("address_line3", ""),
                    city=address_data["city"],
                    postcode=address_data["postcode"],
                    county=address_data["county"],
                    country=address_data["country"],
                    user_ref=user_ref,
                    is_default=False,
                    verified=True,
                )
                address_parent_page.add_child(instance=address_instance)
                address_instance.save()
                address_instances.append(address_instance)
                logger.info(
                    f"Address created for {address_data['address_line1']}, {address_data['city']}."
                )
        except Exception as e:
            logger.error(f"Error fetching or creating address: {str(e)}")

        return address_instances

    def _get_order_ref(self, order_id):
        try:
            order_ref = Order.objects.get(order_id=order_id)
            logger.info(f"Order reference for order_id {order_id} found.")
            return order_ref
        except Order.DoesNotExist:
            logger.warning(f"Order with order_id {order_id} does not exist.")
            return None

    def _get_product_ref(self, product_code):
        try:
            product_ref = Product.objects.get(product_code=product_code)
            logger.info(f"Product reference for product_code {product_code} found.")
            return product_ref
        except Product.DoesNotExist:
            logger.warning(f"Product with product_code {product_code} does not exist.")
            return None

    def _create_order_instance(self, data, order_parent_page):
        try:
            order_instance = Order.objects.get(order_id=data.get("order_id"))
            logger.info(f"Order instance for order_id {data.get('order_id')} found.")
        except Order.DoesNotExist:
            logger.info(
                f"Creating new order instance for order_id {data.get('order_id')}."
            )
            slug = slugify(f"order-{data['order_id']}-{str(uuid.uuid4())}")
            if Order.objects.filter(slug=slug).exists():
                slug = f"{slug}-{str(uuid.uuid4())}"
            order_instance = Order(
                title=f"Order {data['order_id']}",
                slug=slug,
                order_id=data.get("order_id"),
                order_date=data.get("order_date"),
                user_ref=data.get("user_ref", None),
                order_origin=data.get("order_origin").lower(),
                address_ref=data.get("address_ref"),
                tracking_number=data.get("tracking_number", None),
                order_confirmation_number=data.get(
                    "order_confirmation_number",
                    generate_confirmation_number(),
                ),
            )
            order_parent_page.add_child(instance=order_instance)
            order_instance.save()
            logger.info(f"Order created for order_id {data.get('order_id')}.")

        return order_instance

    def _create_order_item_instance(self, data):
        try:
            order_item_instance = OrderItem.objects.get(
                order_item_id=data.get("order_item_id")
            )
            logger.info(
                f"Order item instance for order_item_id {data.get('order_item_id')} found."
            )
        except OrderItem.DoesNotExist:
            logger.info(
                f"Creating new order item instance for order_item_id {data.get('order_item_id')}."
            )
            order_item_instance = OrderItem(
                title=f"Order Item {data['order_item_id']}",
                slug=slugify(f"order-item-{data['order_item_id']}-{str(uuid.uuid4())}"),
                order_item_id=data.get("order_item_id"),
                order_ref=data.get("order_ref"),
                product_ref=data.get("product_ref"),
                quantity=data.get("quantity", 0),
                quantity_inprogress=data.get("quantity_inprogress", 0),
                quantity_shipped=data.get("quantity_shipped", 0),
                quantity_cancelled=data.get("quantity_cancelled", 0),
            )
            data.get("order_ref").add_child(instance=order_item_instance)
            order_item_instance.save()
            logger.info(
                f"Order item created for order_item_id {data.get('order_item_id')}."
            )

        return order_item_instance


class DeleteMigratedOrdersAPIView(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrRegisteredUser]

    def delete(self, request, *args, **kwargs):
        try:
            # Delete all OrderItem instances
            order_items_deleted = OrderItem.objects.all().delete()

            # Delete all Order instances
            orders_deleted = Order.objects.all().delete()

            # Logging for success
            logger.info(
                f"Deleted {order_items_deleted} order items and {orders_deleted} orders."
            )

            return Response(
                {
                    "message": f"Successfully deleted {orders_deleted} orders and {order_items_deleted} order items."
                },
                status=status.HTTP_200_OK,
            )

        except Exception as ex:
            logger.error(f"Error deleting orders: {str(ex)}")
            return Response(
                {"error": f"Failed to delete migrated orders: {str(ex)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


#
