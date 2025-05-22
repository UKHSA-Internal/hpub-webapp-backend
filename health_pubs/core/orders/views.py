import logging
import time
import traceback
import uuid
from datetime import datetime, timedelta

import pandas as pd
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from django.utils.timezone import now
from psycopg2 import errors
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import (
    APIException,
    NotFound,
    ValidationError as DRFValidationError,
)
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.models import Page

from core.addresses.models import Address
from core.addresses.serializers import AddressSerializer
from core.errors.enums import ErrorCode, ErrorMessage
from core.errors.error_function import handle_error
from core.establishments.models import Establishment
from core.event_analytics.models import EventAnalytics
from core.order_limits.models import OrderLimitPage
from core.products.models import Product
from core.roles.models import Role
from core.users.models import User
from core.users.permissions import IsAdminOrRegisteredUser
from core.utils.confirmation_generator import generate_confirmation_number
from core.utils.custom_token_authentication import CustomTokenAuthentication
from core.utils.order_confirmation_generation import generate_order_confirmation
from core.utils.send_order_confirmation import send_notification

from .models import Order, OrderItem
from .serializers import OrderItemSerializer, OrderSerializer

logger = logging.getLogger(__name__)


class OrderViewSet(viewsets.ModelViewSet):

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrRegisteredUser]
    queryset = Order.objects.all()
    serializer_class = OrderSerializer

    @action(detail=False, methods=["post"], url_path="admin")
    def create_for_admin(self, request, *args, **kwargs):
        return self._create_order(request, admin=True)

    def create(self, request, *args, **kwargs):
        return self._create_order(request, admin=False)

    @action(detail=False, methods=["post"], url_path="check-order-limits")
    def check_order_limits(self, request):
        """
        Accepts a list of product_codes and user_ref.
        Returns how many have been ordered in the last 24 hours and what remains.
        """
        user_ref = request.data.get("user_ref")
        product_codes = request.data.get("product_codes")

        if not user_ref or not product_codes:
            return Response(
                {"error": "user_ref and product_codes[] are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user_instance = self._get_user_or_error(user_ref)
            logger.info(f"User instance: {user_instance}")
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        window_start = now() - timedelta(hours=24)
        logger.info(f"Window start time: {window_start}")

        results = []

        for code in product_codes:
            try:
                product = Product.objects.get(product_code=code)
                logger.info(f"Product instance: {product}")
            except Product.DoesNotExist:
                continue

            order_limit_page = OrderLimitPage.objects.filter(
                product_ref=product,
            ).first()
            logger.info(f"Order limit page: {order_limit_page}")

            if not order_limit_page:
                continue

            limit = order_limit_page.order_limit
            logger.info(f"Order limit: {limit}")
            already_ordered = (
                Order.objects.filter(
                    user_ref__organization_ref__organization_id=user_instance.organization_ref.organization_id,
                    order_items__product_ref=product,
                    created_at__gte=window_start,
                ).aggregate(total=Sum("order_items__quantity"))["total"]
                or 0
            )
            logger.info(f"Already ordered quantity: {already_ordered}")

            remaining = max(limit - already_ordered, 0)
            logger.info(f"Remaining quantity:{remaining}")

            results.append(
                {
                    "product_code": code,
                    "title": product.title,
                    "daily_limit": limit,
                    "already_ordered": already_ordered,
                    "remaining": remaining,
                }
            )

        return Response(results, status=status.HTTP_200_OK)

    # Helper methods

    def call_record_reorder_events(self, order_instance, request):
        # Now, record reorder events (if any) for this order.
        try:
            self.record_reorder_events(order_instance, request)
        except Exception as e:
            logger.exception(
                f"Failed to record reorder events for order {order_instance.order_id}: {e}"
            )

    def _get_or_create_analytics_index(self):
        """
        Fetch the Page with slug="event-analytics-index", or create it under
        the root if it doesn't exist yet.
        """
        try:
            return Page.objects.get(slug="event-analytics-index")
        except Page.DoesNotExist:
            root = Page.objects.first()
            analytics_index = Page(
                title="Event Analytics",
                slug="event-analytics-index",
                # Use the EventAnalytics content type so add_child knows what to do
                content_type=ContentType.objects.get_for_model(EventAnalytics),
            )
            root.add_child(instance=analytics_index)
            root.save()
            logger.info("Parent page 'event-analytics-index' created.")
            return analytics_index

    def record_reorder_events(self, order_instance: Order, request):
        """
        For each order item in the given order, if the user has a previous order
        for the same product, record a "reorder" EventAnalytics page under the
        analytics index, so wagtail will set depth/path correctly.
        """
        session_id = request.headers.get("X-Session-ID", "unknown")
        user = order_instance.user_ref

        analytics_index = self._get_or_create_analytics_index()

        for item in order_instance.order_items.all():
            product = item.product_ref

            previous_orders = Order.objects.filter(
                user_ref=user, order_items__product_ref=product
            ).exclude(order_id=order_instance.order_id)
            if not previous_orders.exists():
                continue

            # 1) Instantiate (but do NOT save yet)
            event_page = EventAnalytics(
                title=f"Reorder of {product.title}",
                slug=slugify(f"reorder-{product.product_code}-{uuid.uuid4()}"),
                event_type="reorder",
                user_ref=user,
                session_id=session_id,
                metadata={
                    "order_id": order_instance.order_id,
                    "product_code": product.product_code,
                    "quantity": item.quantity,
                    "timestamp": timezone.now().isoformat(),
                },
            )

            # 2) Add it as a child (this sets path, depth, etc. and saves)
            analytics_index.add_child(instance=event_page)

            logger.info(
                f"Recorded reorder event page (id={event_page.id}) "
                f"for user {user.user_id}, product {product.product_code}"
            )

    def _create_order(self, request, admin=False):
        # 1) Extract and validate raw inputs
        (
            data,
            items,
            address_ref,
            user_ref,
            user_data,
            err,
        ) = self._extract_and_validate_request(request, admin)
        if err:
            return err

        # 2) Get or create the parent page
        try:
            parent = self._get_parent_page(admin)
        except Exception:
            return handle_error(
                ErrorCode.PAGE_CREATION_ERROR,
                ErrorMessage.PAGE_CREATION_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # 3) Prepare the two user roles (order_user + limit_user)
        user_setup = self._prepare_users(admin, user_ref, user_data, data, parent)
        if isinstance(user_setup, Response):
            return user_setup
        order_user, limit_user = user_setup

        # 4) Resolve address if provided
        addr_result = self._resolve_address(address_ref, admin)
        if isinstance(addr_result, Response):
            return addr_result
        address = addr_result

        # 5) Try the atomic create + retry loop
        return self._attempt_create(
            data, items, order_user, limit_user, address, parent, request, admin
        )

    def _extract_and_validate_request(self, request, admin):
        data = request.data.copy()
        items = data.pop("order_items", [])
        address_ref = data.pop("address_ref", None)
        user_ref = data.pop("user_ref", None)
        user_data = data.pop("user_info", None) if admin else None

        # product-live check
        for it in items:
            code = it.get("product_code")
            if not self._is_product_live(code):
                resp = JsonResponse(
                    {
                        "error_code": ErrorCode.PRODUCT_NOT_LIVE.value,
                        "error_message": ErrorMessage.product_not_live(code),
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
                return None, None, None, None, None, resp

        # admin-only presence checks
        if admin:
            if not user_ref:
                return (
                    None,
                    None,
                    None,
                    None,
                    None,
                    handle_error(
                        ErrorCode.USER_REF_REQUIRED,
                        ErrorMessage.USER_REF_REQUIRED,
                        status_code=status.HTTP_400_BAD_REQUEST,
                    ),
                )
            if not user_data:
                return (
                    None,
                    None,
                    None,
                    None,
                    None,
                    handle_error(
                        ErrorCode.USER_INFO_REQUIRED,
                        ErrorMessage.USER_INFO_REQUIRED,
                        status_code=status.HTTP_400_BAD_REQUEST,
                    ),
                )

        return data, items, address_ref, user_ref, user_data, None

    def _get_parent_page(self, admin):
        if admin:
            return self._get_or_create_parent_page()
        return self._get_or_create_parent_page_or_error()

    def _prepare_users(self, admin, user_ref, user_data, data, parent):
        try:
            if admin:
                delivery = self._get_or_create_user(user_data, parent)
                delivery.refresh_from_db()
                owner = self._get_existing_user(user_ref)
                if not getattr(owner.establishment_ref, "full_external_key", None):
                    return JsonResponse(
                        {
                            "error": "User's establishment_ref or full_external_key is missing."
                        },
                        status=status.HTTP_404_NOT_FOUND,
                    )
                data["full_external_key"] = owner.establishment_ref.full_external_key
                primary, limiter = delivery, owner
            else:
                primary = self._get_user_or_error(user_ref)
                if not primary.establishment_ref:
                    return JsonResponse(
                        {"error": "User's establishment_ref is missing."},
                        status=status.HTTP_404_NOT_FOUND,
                    )
                data["full_external_key"] = primary.establishment_ref.full_external_key
                limiter = primary

            if not self._validate_order_limits(data.get("order_items", []), limiter):
                return handle_error(
                    ErrorCode.ORDER_LIMIT_EXCEEDED,
                    ErrorMessage.ORDER_LIMIT_EXCEEDED,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            return primary, limiter

        except IntegrityError:
            code = (
                ErrorCode.USER_CREATION_ERROR
                if admin
                else ErrorCode.INTERNAL_SERVER_ERROR
            )
            msg = (
                ErrorMessage.USER_CREATION_ERROR
                if admin
                else ErrorMessage.INTERNAL_SERVER_ERROR
            )
            status_code = (
                status.HTTP_400_BAD_REQUEST
                if admin
                else status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            return handle_error(code, msg, status_code=status_code)
        except Exception:
            return handle_error(
                ErrorCode.INTERNAL_SERVER_ERROR,
                ErrorMessage.INTERNAL_SERVER_ERROR,
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _resolve_address(self, address_ref, admin):
        if not address_ref:
            return None
        try:
            return Address.objects.get(address_id=address_ref)
        except Address.DoesNotExist:
            if admin:
                return handle_error(
                    ErrorCode.ADDRESS_NOT_FOUND,
                    ErrorMessage.ADDRESS_NOT_FOUND,
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            raise DRFValidationError({"address_ref": ErrorMessage.ADDRESS_NOT_FOUND})

    def _attempt_create(
        self, data, items, order_user, limit_user, address, parent, request, admin
    ):
        for attempt in range(3):
            try:
                with transaction.atomic():
                    locked = Page.objects.select_for_update().get(pk=parent.pk)
                    order = self._create_order_instance(
                        data, order_user, address, locked
                    )
                    self._create_order_items(items, order, locked, order_user)
                    self._update_product_quantities(items)
                    self._notify_and_record(order, request)
                    return Response(
                        self.get_serializer(order).data, status=status.HTTP_201_CREATED
                    )

            except (IntegrityError, DjangoValidationError) as exc:
                if self._is_collision(exc) and attempt < 2:
                    time.sleep(0.1 * (2**attempt))
                    continue
                if admin:
                    return handle_error(
                        ErrorCode.ORDER_CREATION_ERROR,
                        ErrorMessage.ORDER_CREATION_ERROR,
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                raise DRFValidationError({"detail": ErrorMessage.ORDER_CREATION_ERROR})

        # fallback (should never hit)
        return handle_error(
            ErrorCode.INTERNAL_SERVER_ERROR,
            ErrorMessage.INTERNAL_SERVER_ERROR,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def _notify_and_record(self, order, request):
        try:
            send_notification(order)
        except Exception as e:
            logger.warning(f"Email send failed for {order.order_id}: {e}")
        try:
            self.record_reorder_events(order, request)
        except Exception as e:
            logger.error(f"Analytics failed for {order.order_id}: {e}")

    def _is_collision(self, exc):
        return (isinstance(exc, IntegrityError) and self._is_path_collision(exc)) or (
            isinstance(exc, DjangoValidationError)
            and self._is_validation_path_collision(exc)
        )

    def _is_path_collision(self, err: IntegrityError) -> bool:
        cause = getattr(err, "__cause__", None)
        return (
            isinstance(cause, errors.UniqueViolation)
            and getattr(cause.diag, "constraint_name", "")
            == "wagtailcore_page_path_key"
        )

    def _is_validation_path_collision(self, err: DjangoValidationError) -> bool:
        md = getattr(err, "message_dict", {})
        return "path" in md and any("already exists" in m for m in md["path"])

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
        logger.info("Validating order limits...")
        # Define the 24-hour window start
        window_start = now() - timedelta(hours=24)

        # Accumulate requested quantities by product code
        product_quantities = {}
        for item in items_data:
            product_code = item["product_code"]
            quantity = item["quantity"]
            product_quantities[product_code] = (
                product_quantities.get(product_code, 0) + quantity
            )

        for product_code, requested_quantity in product_quantities.items():
            try:
                product = Product.objects.get(product_code=product_code)
            except Product.DoesNotExist:
                logger.error(f"Product not found: {product_code}")
                raise DRFValidationError(
                    {
                        "product_code": f"Product with code {product_code} does not exist."
                    }
                )

            # Retrieve the order limit for this product
            limit_page = OrderLimitPage.objects.filter(
                organization_ref=user_instance.organization_ref.organization_id,
                product_ref=product,
            ).first()

            if not limit_page:
                continue  # No limit set, allow order

            daily_limit = limit_page.order_limit

            # Calculate quantity already ordered in the past 24 hours
            quantity_ordered_recently = (
                Order.objects.filter(
                    user_ref__organization_ref__organization_id=user_instance.organization_ref.organization_id,
                    order_items__product_ref=product,
                    created_at__gte=window_start,
                ).aggregate(total=Sum("order_items__quantity"))["total"]
                or 0
            )

            if quantity_ordered_recently + requested_quantity > daily_limit:
                remaining = max(daily_limit - quantity_ordered_recently, 0)
                logger.warning(
                    f"24h limit exceeded for {product_code}: limit={daily_limit}, "
                    f"already_ordered={quantity_ordered_recently}, requested={requested_quantity}"
                )
                raise DRFValidationError(
                    {
                        "error_message": (
                            f"You've already ordered {quantity_ordered_recently} copies of '{product.title}' today. "
                            f"You can only order {remaining} more in the next 24 hours."
                        ),
                        "error_code": "ORDER_LIMIT_EXCEEDED",
                        "order_limit": daily_limit,
                        "current_total_today": quantity_ordered_recently,
                        "requested_quantity": requested_quantity,
                    }
                )

        return True

    def _update_product_quantities(self, items_data):
        logger.info("Updating product quantities...")
        for item in items_data:
            product = item.get("product_ref")
            logger.info(f"Product: {product}")
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
                new_uuid = str(uuid.uuid4())
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
            user_id=str(uuid.uuid4()),
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
        logger.info(f"Creating order items for order {order_instance.order_id}...")

        for item_data in items_data:
            product_code = item_data.get("product_code")

            if product_code:
                try:
                    product_instance = Product.objects.get(product_code=product_code)

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
            raise DRFValidationError({"user_ref": ErrorMessage.USER_NOT_PROVIDED})

        try:
            user = User.objects.get(user_id=user_ref)
            # if not user.is_authorized:
            #     logger.warning(f"User with ID {user_ref} is not authorized.")
            #     raise PermissionDenied(ErrorMessage.USER_NOT_AUTHORIZED)
            return user
        except User.DoesNotExist:
            logger.warning(f"No user found with ID {user_ref}")
            raise DRFValidationError({"user_ref": ErrorMessage.USER_NOT_FOUND})

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
            raise DRFValidationError(address_serializer.errors)

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
            raise DRFValidationError(ErrorMessage.ADDRESS_CREATION_ERROR)
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
            raise DRFValidationError({"product_code": ErrorMessage.PRODUCT_NOT_FOUND})

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


class MigrateOrdersAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        logger.info("Starting the order migration process.")

        orders_file = request.FILES.get("orders_excel")
        order_items_file = request.FILES.get("order_items_excel")
        if not orders_file or not order_items_file:
            logger.error("Both orders and order items files are required.")
            return JsonResponse(
                {"error": "Both orders and order items files are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            orders_df = pd.read_excel(orders_file)
            order_items_df = pd.read_excel(order_items_file)
            logger.info("Excel files successfully read.")
        except Exception as e:
            logger.error(f"Error reading Excel files: {e}")
            return JsonResponse(
                {"error": "Failed to read the provided Excel files."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate required columns
        for col in ("order_id", "order_date", "user_id", "order_origin"):
            if col not in orders_df.columns:
                return JsonResponse(
                    {"error": f"Missing required column in orders: {col}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        for col in ("order_item_id", "order_id", "ProductCode", "order_line_quantity"):
            if col not in order_items_df.columns:
                return JsonResponse(
                    {"error": f"Missing required column in order items: {col}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Ensure Wagtail parent pages exist
        address_parent = self.get_or_create_parent_page("addresses", "Addresses")
        order_parent = self.get_or_create_parent_page("orders", "Orders")

        # Map original order_id → new UUID
        id_map = {}

        # --- Migrate Orders ---
        for _, row in orders_df.iterrows():
            orig_id = row["order_id"]
            user_ref = self._get_user_ref(row["user_id"])
            if not user_ref:
                logger.warning(
                    f"User {row['user_id']} not found → skipping order {orig_id}"
                )
                continue

            addresses = self._get_or_create_addresses(row, address_parent)
            if not addresses:
                logger.warning(f"No address created for order {orig_id} → skipping")
                continue

            # Generate or reuse a UUID for this order
            new_uuid = id_map.setdefault(orig_id, str(uuid.uuid4()))

            # Common data to set/update
            order_data = {
                "order_date": pd.to_datetime(row["order_date"], dayfirst=True),
                "user_ref": user_ref,
                "order_origin": row["order_origin"].lower(),
                "tracking_number": row.get("tracking_number") or None,
                "order_confirmation_number": row.get("order_confirmation_number")
                or generate_confirmation_number(),
            }

            # There may be multiple address variants per order; create/update one per address
            for addr in addresses:
                order_data["address_ref"] = addr
                self._create_or_update_order(new_uuid, order_data, order_parent)

        # --- Migrate OrderItems ---
        for _, row in order_items_df.iterrows():
            orig_order = row["order_id"]
            new_order_id = id_map.get(orig_order)
            if not new_order_id:
                logger.warning(
                    f"Order item {row['order_item_id']} → no matching order; skipping"
                )
                continue

            order_ref = self._get_order_ref(new_order_id)
            if not order_ref:
                logger.warning(
                    f"Order ref {new_order_id} missing → skipping item {row['order_item_id']}"
                )
                continue

            item_uuid = row["order_item_id"]
            item_data = {
                "order_ref": order_ref,
                "product_ref": self._get_product_ref(row["ProductCode"]),
                "quantity": row["order_line_quantity"],
                "quantity_inprogress": row.get("quantity_inprogress", 0),
                "quantity_shipped": row.get("quantity_shipped", 0),
                "quantity_cancelled": row.get("quantity_cancelled", 0),
            }
            self._create_or_update_order_item(item_uuid, item_data)

        return JsonResponse(
            {"message": "Migration completed successfully."}, status=status.HTTP_200_OK
        )

    def get_or_create_parent_page(self, slug, title):
        try:
            return Page.objects.get(slug=slug)
        except Page.DoesNotExist:
            root = Page.objects.first()
            page = Page(
                title=title,
                slug=slug,
                content_type=ContentType.objects.get_for_model(Page),
            )
            root.add_child(instance=page)
            page.save()
            logger.info(f"Created parent page '{title}'")
            return page

    def _get_user_ref(self, user_id):
        return User.objects.filter(user_id=user_id).first()

    def _get_or_create_addresses(self, row, parent_page):
        addr_attrs = dict(
            address_line1=row["shipping_address_line_1"],
            address_line2=row.get("shipping_address_line_2", ""),
            address_line3=row.get("shipping_address_line_3", ""),
            city=row["shipping_address_city"],
            postcode=row["shipping_address_postcode"],
            county=row.get("shipping_address_county", ""),
            country=row["shipping_address_country"],
        )
        qs = Address.objects.filter(**addr_attrs)
        if qs.exists():
            return list(qs)

        user_ref = self._get_user_ref(row["user_id"])
        if not user_ref:
            return []

        addr = Address(
            title=f"{addr_attrs['address_line1']}, {addr_attrs['city']}",
            slug=slugify(
                f"{addr_attrs['city']}-{addr_attrs['postcode']}-{uuid.uuid4()}"
            ),
            **addr_attrs,
            user_ref=user_ref,
            is_default=False,
            verified=True,
        )
        parent_page.add_child(instance=addr)
        addr.save()
        logger.info(f"Created Address {addr.pk} for order")
        return [addr]

    def _get_order_ref(self, order_id):
        return Order.objects.filter(order_id=order_id).first()

    def _get_product_ref(self, code):
        return Product.objects.filter(product_code=code).first()

    def _create_or_update_order(self, order_id, data, parent_page):
        # Try to load existing...
        order = Order.objects.filter(order_id=order_id).first()
        if order:
            # Update fields only
            for field, val in data.items():
                setattr(order, field, val)
            order.save()
            logger.info(f"Updated Order {order_id}")
        else:
            # Create new Wagtail page under parent
            order = Order(
                title=f"Order {order_id}",
                slug=slugify(f"order-{order_id}-{uuid.uuid4()}"),
                order_id=order_id,
                **data,
            )
            parent_page.add_child(instance=order)
            order.save()
            logger.info(f"Created Order {order_id}")

        return order

    def _create_or_update_order_item(self, item_id, data):
        item = OrderItem.objects.filter(order_item_id=item_id).first()
        if item:
            for field, val in data.items():
                setattr(item, field, val)
            item.save()
            logger.info(f"Updated OrderItem {item_id}")
        else:
            item = OrderItem(
                title=f"Order Item {item_id}",
                slug=slugify(f"order-item-{item_id}-{uuid.uuid4()}"),
                order_item_id=item_id,
                **data,
            )
            data["order_ref"].add_child(instance=item)
            item.save()
            logger.info(f"Created OrderItem {item_id}")

        return item


#
