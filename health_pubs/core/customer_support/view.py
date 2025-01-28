import logging
from datetime import datetime
import uuid

from core.utils.send_contact_us_notification_email import send_notification
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from wagtail.models import Page

from .models import CustomerSupport
from .serializers import CustomerSupportSerializer

logger = logging.getLogger(__name__)


class CustomerSupportViewSet(viewsets.ModelViewSet):
    authentication_classes = [SessionAuthentication, CustomTokenAuthentication]
    permission_classes = [AllowAny]
    queryset = CustomerSupport.objects.all()
    serializer_class = CustomerSupportSerializer

    def create(self, request, *args, **kwargs):
        # Extract title or use a default value
        title = request.data.get("title", "Customer Support")
        slug = slugify(title + "-" + str(uuid.uuid4()) + "-" + str(datetime.now()))

        # Retrieve or create the parent page for customer support
        try:
            parent_page = Page.objects.get(slug="customer-support")
            logger.info("Parent page 'customer-support' found.")
        except Page.DoesNotExist:
            try:
                root_page = Page.objects.first()
                parent_page = Page(
                    title="Customer Support",
                    slug="customer-support",
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)
                parent_page.save()  # Make sure the parent page is saved
                logger.info("Parent page 'customer-support' created.")
            except Exception as ex:
                logger.error("Failed to create parent page: %s", str(ex))
                return Response(
                    {"error": "Failed to create parent page."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        serializer = CustomerSupportSerializer(data=request.data)
        if serializer.is_valid():
            # Extract validated data from serializer
            data = serializer.validated_data

            # Check if the user is authenticated
            if request.user and request.user.is_authenticated:
                # Get contact details from user information
                contact_name = f"{request.user.first_name} {request.user.last_name}"
                contact_email = request.user.email
            else:
                # If the user is not logged in, check for contact_name and contact_email in the request
                contact_name = data.get("contact_name")
                contact_email = data.get("contact_email")
                summary = data.get("summary")

                if not contact_name or not contact_email or not summary:
                    return Response(
                        {
                            "error": "contact_name, contact_email and summary are required for unauthenticated requests."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # Create the new CustomerSupport page
            customer_support_instance = CustomerSupport(
                title=title,
                slug=slug,
                customer_support_id=data.get("customer_support_id"),
                user_ref=data.get("user_ref"),
                message=data.get("message", ""),
                summary=data.get("summary", ""),
                contact_name=contact_name,
                contact_email=contact_email,
            )

            try:
                parent_page.add_child(instance=customer_support_instance)
                customer_support_instance.save()
                logger.info("CustomerSupport page created successfully.")

                # Call the send_notification function
                notification_response = send_notification(
                    contact_name=contact_name,
                    contact_email=contact_email,
                    summary=data.get("summary"),
                    message=data.get("message", ""),
                )

                # Log the notification response
                logger.info(notification_response[0])
                return JsonResponse(
                    CustomerSupportSerializer(customer_support_instance).data,
                    status=201,
                )
            except Exception as e:
                logger.error(f"Error adding customer support as child page: {str(e)}")
                return Response(
                    {"error": "Failed to create customer support page."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


#
