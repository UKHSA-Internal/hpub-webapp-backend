import logging
import os
import sys
import uuid

import pandas as pd
import requests
from configs.get_secret_config import Config
from core.errors.enums import ErrorCode, ErrorMessage
from core.users.models import User
from core.users.permissions import IsAdminOrRegisteredUser
from core.utils.address_verification import get_oauth_token, verify_address
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.contrib.contenttypes.models import ContentType
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page

from .models import Address
from .serializers import AddressSerializer

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)

logger = logging.getLogger(__name__)


class CustomPagination(PageNumberPagination):
    page_size = 20  # Set pagination to 20 items per page

    def get_paginated_response(self, data):
        response = Response(
            {
                "links": {
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
                "count": self.page.paginator.count,
                "results": data,
            }
        )
        response.status_code = 200

        return response


class AddressViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrRegisteredUser]
    queryset = Address.objects.all()
    serializer_class = AddressSerializer
    config = Config()
    pagination_class = CustomPagination

    # Initialize base_url in the constructor

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = self.config.get_address_verify_base_url()

    def create(self, request, *args, **kwargs):
        data = request.data

        # Handle user_ref
        user_ref = None
        user_ref_id = data.get("user_ref")
        if user_ref_id:
            user_ref = get_object_or_404(User, user_id=user_ref_id)

        # Check for existing address
        existing_address = Address.objects.filter(
            address_line1=data["address_line1"],
            address_line2=data.get("address_line2", ""),
            address_line3=data.get("address_line3", ""),
            city=data["city"],
            postcode=data["postcode"],
            country=data["country"],
            user_ref=user_ref,
        ).first()

        if existing_address:
            return Response(
                {
                    "message": "Address already exists.",
                    "address": AddressSerializer(existing_address).data,
                    "action": "confirm_existing_or_create_new",
                },
                status=status.HTTP_409_CONFLICT,
            )

        # Generate slug and title
        slug = self.get_unique_slug(slugify(data["address_line1"]))
        title = data["address_line1"]

        # Ensure parent page exists
        parent_page = self._get_or_create_parent_page("addresses")

        if not parent_page:
            return Response(
                {"error": "Parent page not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Handle the case where there are no existing children
        if parent_page.get_last_child() is None:
            # Manually create the path and depth for the first child
            path = f"{parent_page.path}0001"
            depth = parent_page.depth + 1
            address_instance = Address(
                title=title,
                slug=slug,
                address_line1=data["address_line1"],
                address_line2=data.get("address_line2"),
                address_line3=data.get("address_line3"),
                city=data["city"],
                county=data.get("county"),
                postcode=data["postcode"],
                country=data["country"],
                is_default=data.get("is_default", False),
                verified=False,
                user_ref=user_ref,
                path=path,
                depth=depth,
            )
            address_instance.save()
        else:
            # Use add_child() for subsequent children
            address_instance = Address(
                title=title,
                slug=slug,
                address_line1=data["address_line1"],
                address_line2=data.get("address_line2"),
                address_line3=data.get("address_line3"),
                city=data["city"],
                county=data.get("county"),
                postcode=data["postcode"],
                country=data["country"],
                is_default=data.get("is_default", False),
                verified=False,
                user_ref=user_ref,
            )
            parent_page.add_child(instance=address_instance)

        # Verify the address using the external API
        verify_address(address_instance)

        # Serialize and return the response
        serializer = AddressSerializer(address_instance)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def _get_or_create_parent_page(self, slug):
        """Ensure the parent page exists; create if it does not."""
        try:
            return Page.objects.get(slug=slug)
        except Page.DoesNotExist:
            root_page = Page.objects.first()
            parent_page = Page(
                title=slug.capitalize(),
                slug=slug,
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            logger.info(f"Parent page '{slug}' created.")
            return parent_page

    def get_unique_slug(self, base_slug):
        """Generate a unique slug for the Address."""
        queryset = Address.objects.filter(slug__startswith=base_slug)
        if not queryset.exists():
            return base_slug

        num = queryset.count() + 1
        return f"{base_slug}-{num}"

    @action(detail=False, methods=["post"], url_path="verify-address")
    def verify(self, request):
        """
        Custom action to verify an address by calling the matchAddress API.
        """
        data = request.data
        postcode = data.get("postcode")
        building_number = data.get("building_number")

        if not postcode or not building_number:
            return Response(
                {"error": "Postcode and building number are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Concatenate building number and postcode into the address
        address = f"{building_number} {postcode}".strip()

        # Prepare the matchAddress payload
        match_address_payload = {
            "operationId": "matchAddress",
            "callingApplication": "HPUB",
            "address": address,
            "maxResults": 100,
            "fuzzy": True,
        }

        # Obtain OAuth token
        token = get_oauth_token()

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "PythonDevApplication",
        }

        # Call matchAddress API
        match_address_url = f"{self.base_url}/matchAddress"
        match_response = requests.post(
            match_address_url, json=match_address_payload, headers=headers
        )

        logging.info("Match Address Response:", match_response.json())
        if match_response.status_code == 200:
            # Filter to only include addresses in England (countryCode = "E") and matching the same postcode
            matched_addresses = [
                addr
                for addr in match_response.json().get("matchedAddresses", [])
                if addr.get("countryCode") in ["E", "England"] and addr.get("postcode") == postcode
            ]
            if not matched_addresses:
                # If no addresses match the criteria, return an error
                return Response(
                    {
                        "error": "No addresses found in England with the provided postcode. Please select a valid address."
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            return Response(
                {"matchedAddresses": matched_addresses}, status=status.HTTP_200_OK
            )
        else:
            return Response(
                {"error": "Failed to verify address", "details": match_response.json()},
                status=status.HTTP_400_BAD_REQUEST,
            )


    @action(detail=False, methods=["post"], url_path="geo-code-address")
    def geo_code_address(self, request):
        """
        Custom action to get geocode information for an address by calling the geoCodeAddresses API.
        """
        data = request.data
        address_string = data.get("address_string", "")
        postcode = data.get("postcode", "")
        uprn = data.get("uprn", "")

        if not address_string and not postcode:
            return Response(
                {"error": "Either address string or postcode is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Prepare the geoCodeAddresses payload
        geo_code_payload = {
            "operationId": "geoCodeAddresses",
            "callingApplication": "HPUB",
            "addressString": address_string,
            "uprn": uprn,
            "postcode": postcode,
        }

        # Obtain OAuth token
        try:
            token = get_oauth_token()
        except Exception as e:
            return Response(
                {"error": "Failed to obtain OAuth token", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "PythonDevApplication",
        }

        # Call geoCodeAddresses API
        geo_code_url = f"{self.base_url}/geoCodeAddresses"
        try:
            geo_response = requests.post(
                geo_code_url, json=geo_code_payload, headers=headers
            )
            geo_response.raise_for_status()  # Raise an error for bad HTTP status codes
        except requests.exceptions.HTTPError as http_err:
            return Response(
                {
                    "error": "HTTP error",
                    "details": str(http_err),
                    "status_code": geo_response.status_code,
                },
                status=geo_response.status_code,
            )
        except Exception as e:
            return Response(
                {"error": "An unexpected error occurred", "details": str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Process successful response and filter by postcode
        results = geo_response.json().get("matchedAddresses", [])
        matched_addresses = [
            {
                "addressString": result["addressString"],
                "postcode": result["postcode"],
                "uprn": result.get("uprn", ""),
                "parentUprn": result.get("parentUprn", ""),
                "blpuCode": result.get("blpuCode", ""),
                "locationX": result.get("locationX", ""),
                "locationY": result.get("locationY", ""),
                "latitude": result.get("latitude", ""),
                "longitude": result.get("longitude", ""),
            }
            for result in results
            if result.get("postcode") == postcode
            and (result.get("countryCode") in ["E", "England"])
        ]
        if not matched_addresses:
            return Response(
                {
                    "error": "No addresses found in England. Please select an address in England only."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"matchedAddresses": matched_addresses}, status=status.HTTP_200_OK
        )

    def update(self, request, *args, **kwargs):
        # Extract address_id from URL kwargs
        address_id = kwargs.get("pk")

        try:
            # Retrieve the Address instance using address_id
            instance = Address.objects.get(id=address_id)
        except Address.DoesNotExist:
            # Handle case where Address with address_id does not exist
            return Response(
                {
                    "error": ErrorCode.NOT_FOUND.value,
                    "message": ErrorMessage.NOT_FOUND.value,
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Serialize the incoming data with partial updates
        serializer = AddressSerializer(data=request.data, partial=True)
        if serializer.is_valid():
            data = serializer.validated_data

            # Check for duplicate addresses
            existing_address = (
                Address.objects.exclude(id=address_id)
                .filter(
                    address_line1=data.get("address_line1", instance.address_line1),
                    city=data.get("city", instance.city),
                    postcode=data.get("postcode", instance.postcode),
                    country=data.get("country", instance.country),
                    user_ref=data.get("user_ref", instance.user_ref),
                )
                .first()
            )

            if existing_address:
                return Response(
                    {"error": "Address already exists"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Update the existing Address instance
            instance.address_line1 = data.get("address_line1", instance.address_line1)
            instance.address_line2 = data.get("address_line2", instance.address_line2)
            instance.address_line3 = data.get("address_line3", instance.address_line3)
            instance.city = data.get("city", instance.city)
            instance.county = data.get("county", instance.county)
            instance.postcode = data.get("postcode", instance.postcode)
            instance.country = data.get("country", instance.country)
            instance.is_default = data.get("is_default", instance.is_default)
            instance.verified = data.get("verified", instance.verified)

            # Update slug and title
            instance.title = "address-title"
            instance.slug = self.get_unique_slug(instance.title)

            # Handle creation if the instance is new
            if not instance.pk:
                # Determine the parent page for this Address instance
                parent_page = Page.objects.get(
                    slug="addresses"
                )  # Adjust the slug as needed

                # Use _add_child to add instance to parent
                parent_page._add_child(instance=instance)
            else:
                # Save updates to the existing instance
                instance.save()

            # Return the updated serialized data
            updated_serializer = AddressSerializer(instance)
            return Response(updated_serializer.data, status=status.HTTP_200_OK)

        # Return errors if validation fails
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["get"], url_path=r"user/(?P<user_id>[\w-]+)")
    def list_by_user(self, request, user_id=None):
        """
        List all addresses for the user with the provided id.
        """
        try:
            User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return Response(
                {
                    "error": "USER_NOT_FOUND",
                    "message": "User with the provided ID does not exist.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        # Retrieve addresses for the user
        user_addresses = Address.objects.filter(user_ref=user_id)

        if not user_addresses.exists():
            return Response(
                {
                    "error": "NO_ADDRESSES_FOUND",
                    "message": "No addresses found for this user.",
                },
                status=status.HTTP_404_NOT_FOUND,
            )

        serializer = self.get_serializer(user_addresses, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request):
        # Get the file from the request
        addresses_file = request.FILES.get("addresses_excel")

        if not addresses_file:
            return JsonResponse(
                {"error": "The addresses file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Read the Excel file
        try:
            addresses_df = pd.read_excel(addresses_file)
        except Exception as e:
            logger.error(f"Error reading the Excel file: {str(e)}")
            return JsonResponse(
                {"error": "Failed to read the provided Excel file."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check for required columns in the addresses file
        required_fields = ["address_line1", "city", "postcode", "country", "user_id"]
        for field in required_fields:
            if field not in addresses_df.columns:
                return JsonResponse(
                    {"error": f"Missing required field in addresses file: {field}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Get or create the parent page for addresses
        address_parent_page = self._get_or_create_parent_page("addresses")

        # Process and create addresses
        for _, row in addresses_df.iterrows():
            address_data = {
                "address_id": (
                    row["address_id"]
                    if pd.notnull(row["address_id"])
                    else str(uuid.uuid4())
                ),
                "address_line1": row["address_line1"],
                "address_line2": row.get("address_line2", ""),
                "address_line3": row.get("address_line3", ""),
                "city": row["city"],
                "county": row.get("county", ""),
                "postcode": row["postcode"],
                "country": row["country"],
                "user_id": row["user_id"],
                "is_default": row.get("is_default", False),
                "verified": row.get("verified", False),
            }
            self._create_or_update_address(address_data, address_parent_page)

        return JsonResponse(
            {"message": "Address bulk upload completed successfully."},
            status=status.HTTP_200_OK,
        )

    def _create_or_update_address(self, data, address_parent_page):
        # Retrieve the user reference
        try:
            user_ref = User.objects.get(user_id=data["user_id"])
        except User.DoesNotExist:
            logger.error(f"User not found for user_id {data['user_id']}")
            return None

        # Check if the address already exists
        try:
            address_instance = Address.objects.get(
                address_line1=data["address_line1"],
                city=data["city"],
                postcode=data["postcode"],
                user_ref=user_ref,
            )
            logger.info(
                f"Address already exists for {data['address_line1']}, updating details."
            )
        except Address.DoesNotExist:
            # Create a new Address instance
            title = f"{data['address_line1']}, {data['city']}"
            slug = slugify(
                f"{data['city']}-{data['postcode']}-{uuid.uuid4()}"
            )  # Unique slug

            address_instance = Address(
                title=title,
                slug=slug,
                address_line1=data["address_line1"],
                address_line2=data.get("address_line2"),
                address_line3=data.get("address_line3"),
                city=data["city"],
                county=data.get("county"),
                postcode=data["postcode"],
                country=data["country"],
                is_default=data.get("is_default"),
                verified=data.get("verified"),
                user_ref=user_ref,
            )
            address_parent_page.add_child(
                instance=address_instance
            )  # Automatically handles path
            address_instance.save()
            logger.info(f"Address added as a child successfully: {address_instance}")

        return address_instance

    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request, *args, **kwargs):
        try:
            # Retrieve all Address entries
            entries = Address.objects.all()

            if not entries.exists():
                return Response(
                    {"message": "No entries found to delete."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Delete all entries
            count = entries.delete()

            logger.info(f"Deleted all Address entries successfully. Count: {count}")
            return Response(
                {"message": f"Successfully deleted {count} entries."},
                status=status.HTTP_200_OK,
            )
        except Exception as e:
            logger.error(f"Error deleting entries: {str(e)}")
            return Response(
                {"error": f"Failed to delete entries: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def list(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        page = self.paginate_queryset(queryset)

        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


#


#
