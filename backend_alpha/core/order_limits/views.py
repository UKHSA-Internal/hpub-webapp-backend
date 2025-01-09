import uuid

from core.organizations.models import Organization
from core.products.models import Product
from core.users.permissions import IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page

from .models import OrderLimitPage
from .serializers import OrderLimitPageSerializer


class OrderLimitPageViewSet(viewsets.ModelViewSet):

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = OrderLimitPage.objects.all()
    serializer_class = OrderLimitPageSerializer

    def create(self, request, *args, **kwargs):
        data = request.data

        # Check if the data is a list or a single entry
        if isinstance(data, dict):
            data_list = [data]  # Wrap single object in a list for uniform handling
        elif isinstance(data, list):
            data_list = data
        else:
            return Response(
                {
                    "error": "Expected a list of order limits or a single order limit object"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_order_limits = []
        errors = []

        # Find or create the parent page
        try:
            parent_page = Page.objects.get(slug="order-limits")
        except Page.DoesNotExist:
            root_page = Page.objects.first()
            parent_page = Page(
                title="Order Limits",
                slug="order-limits",
                content_type=Page.content_type.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)

        # Loop through each order limit data in the list
        for data in data_list:
            # Validate order_limit
            order_limit = data.get("order_limit", None)
            if order_limit is None:
                errors.append({"error": "Order limit is required", "data": data})
                continue

            # Validate product_ref
            product_id = data.get("product_ref", None)
            if not product_id:
                errors.append({"error": "Product reference is required", "data": data})
                continue

            try:
                product = Product.objects.get(product_id=product_id)
            except Product.DoesNotExist:
                errors.append({"error": "Product does not exist", "data": data})
                continue

            # Validate organization_ref
            organization_id = data.get("organization_ref", None)
            if not organization_id:
                errors.append(
                    {"error": "Organization reference is required", "data": data}
                )
                continue

            try:
                organization = Organization.objects.get(organization_id=organization_id)
            except Organization.DoesNotExist:
                errors.append({"error": "Organization does not exist", "data": data})
                continue

            # Create OrderLimitPage instance dynamically
            try:
                order_limit_page = OrderLimitPage(
                    title=f"Order Limit {uuid.uuid4()}",
                    slug=f"order-limit-{uuid.uuid4()}",
                    order_limit_id=data.get("order_limit_id", str(uuid.uuid4())),
                    order_limit=order_limit,
                    product_ref=product,
                    organization_ref=organization,
                )

                # Add the order_limit_page as a child of the parent page
                parent_page.add_child(instance=order_limit_page)
                order_limit_page.save()

                created_order_limits.append(
                    {
                        "order_limit_id": order_limit_page.order_limit_id,
                        "order_limit": order_limit_page.order_limit,
                        "product_ref": order_limit_page.product_ref.id,
                        "organization_ref": order_limit_page.organization_ref.id,
                    }
                )
            except Exception as e:
                errors.append({"error": str(e), "data": data})

        # Prepare response
        if created_order_limits:
            return Response(
                {"created_order_limits": created_order_limits, "errors": errors},
                status=(
                    status.HTTP_201_CREATED
                    if not errors
                    else status.HTTP_207_MULTI_STATUS
                ),
            )
        else:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, *args, **kwargs):
        data = request.data
        order_limit_id = kwargs.get(
            "pk"
        )  # Assuming the order_limit_id is passed as a URL parameter

        # Fetch the existing OrderLimitPage instance by order_limit_id
        try:
            order_limit_page = OrderLimitPage.objects.get(order_limit_id=order_limit_id)
        except OrderLimitPage.DoesNotExist:
            return Response({"error": "OrderLimitPage does not exist"}, status=404)

        # Validate and update the order_limit
        order_limit = data.get("order_limit", None)
        if order_limit is None:
            return Response({"error": "Order limit is required"}, status=400)

        # Validate and update the product reference by product_id
        product_id = data.get("product_ref", None)
        if product_id:
            try:
                product = Product.objects.get(product_id=product_id)
                order_limit_page.product_ref = product
            except Product.DoesNotExist:
                return Response({"error": "Product does not exist"}, status=400)

        # Validate and update the organization reference by organization_id
        organization_id = data.get("organization_ref", None)
        if organization_id:
            try:
                organization = Organization.objects.get(organization_id=organization_id)
                order_limit_page.organization_ref = organization
            except Organization.DoesNotExist:
                return Response({"error": "Organization does not exist"}, status=400)

        # Update the order limit value
        order_limit_page.order_limit = order_limit

        # Save the updated OrderLimitPage instance
        order_limit_page.save()

        # Return a success response
        return Response(
            {
                "order_limit_id": order_limit_page.order_limit_id,
                "order_limit": order_limit_page.order_limit,
                "product_ref": (
                    order_limit_page.product_ref.product_id
                    if order_limit_page.product_ref
                    else None
                ),
                "organization_ref": (
                    order_limit_page.organization_ref.organization_id
                    if order_limit_page.organization_ref
                    else None
                ),
            },
            status=200,
        )


#
