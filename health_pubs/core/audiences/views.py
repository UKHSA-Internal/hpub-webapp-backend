import logging

import pandas as pd
from core.users.permissions import IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import slugify
from django.utils.timezone import now
from django.shortcuts import get_object_or_404
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page

from .models import Audience
from .serializers import AudienceSerializer

logger = logging.getLogger(__name__)


class AudienceCreateViewSet(viewsets.ModelViewSet):
    queryset = Audience.objects.all()
    serializer_class = AudienceSerializer
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def create(self, request, *args, **kwargs):
        try:
            parent_page = Page.objects.get(slug="audiences")
        except Page.DoesNotExist:
            root_page = Page.objects.first()
            parent_page = Page(
                title="Audiences",
                slug="audiences",
                content_type=root_page.content_type,
            )
            root_page.add_child(instance=parent_page)
            parent_page.save()

        audiences_data = (
            request.data if isinstance(request.data, list) else [request.data]
        )
        created_audiences = []

        for audience_data in audiences_data:
            title = "Audience Title"
            slug = slugify(f"{title}-{now()}")
            serializer = AudienceSerializer(data=audience_data)
            if serializer.is_valid():
                data = serializer.validated_data
                audience_instance = Audience(
                    audience_id=data.get("audience_id"),
                    title=title,
                    slug=slug,
                    name=data.get("name"),
                    key=data.get("key"),
                    description=data.get("description", ""),
                )
                parent_page.add_child(instance=audience_instance)
                audience_instance.save()
                created_audiences.append(AudienceSerializer(audience_instance).data)
            else:
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        return Response(created_audiences, status=status.HTTP_201_CREATED)


class AudienceListViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = Audience.objects.all()
    serializer_class = AudienceSerializer

    def list(self, request):
        ser = self.get_serializer(self.get_queryset(), many=True)
        return Response(ser.data)

    def retrieve(self, request, pk=None):
        try:
            audience = Audience.objects.get(audience_id=pk)
        except Audience.DoesNotExist:
            return Response({"error": "Audience not found"}, status=404)

        ser = self.get_serializer(audience)
        return Response(ser.data)


class AudienceUpdateViewSet(viewsets.ViewSet):
    """
    Update or partially update Audience entry.
    Supports PUT and PATCH.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def update(self, request, pk=None):
        instance = get_object_or_404(Audience, pk=pk)
        serializer = AudienceSerializer(instance, data=request.data, partial=False)

        serializer.is_valid(raise_exception=True)

        for attr, value in serializer.validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return Response(serializer.data)

    def partial_update(self, request, pk=None):
        instance = get_object_or_404(Audience, pk=pk)
        serializer = AudienceSerializer(instance, data=request.data, partial=True)

        serializer.is_valid(raise_exception=True)

        for attr, value in serializer.validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        return Response(serializer.data)


class AudienceBulkUploadViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request, *args, **kwargs):
        # Retrieve or create the parent page
        try:
            parent_page = Page.objects.get(slug="audience-bulk")
            logger.info("Parent page 'audience-bulk' found.")
        except Page.DoesNotExist:
            try:
                root_page = Page.objects.first()
                parent_page = Page(
                    title="AudienceBulk",
                    slug="audience-bulk",
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)
                logger.info("Parent page 'audience-bulk' created.")
            except Exception as ex:
                logger.error("Failed to create parent page: %s", str(ex))
                return Response(
                    {"error": "Failed to create parent page."},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Check if parent page is valid
        if not isinstance(parent_page, Page):
            return Response(
                {"error": "Parent page could not be retrieved or created."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Upload Excel file
        excel_file = request.FILES.get("excel_file")
        if not excel_file:
            return Response(
                {"error": "Excel file is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check the file extension
        if not (excel_file.name.endswith(".xlsx") or excel_file.name.endswith(".xls")):
            return Response(
                {
                    "error": "File is not a valid Excel file. Please upload an .xlsx or .xls file."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Read Excel file using pandas
        try:
            df = pd.read_excel(excel_file)
        except Exception as e:
            logger.error(f"Error reading Excel file: {str(e)}")
            return Response(
                {"error": f"Failed to read the Excel file: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_entries = []
        errors = []

        for index, row in df.iterrows():
            name = row.get("name")
            key = row.get("key")
            description = row.get("description")
            audience_id = row.get("id")
            logger.info("Audience ID", audience_id)

            if pd.isna(name) or pd.isna(key):
                error_msg = f"Missing name or key for entry at row {index + 1}."
                errors.append({"error": error_msg})
                logger.warning(error_msg)
                return Response(
                    {"errors": errors}, status=status.HTTP_400_BAD_REQUEST
                )  # Stop processing

            # Check if the entry already exists
            if Audience.objects.filter(key=key).exists():
                error_msg = f'Entry with key "{key}" already exists at row {index + 1}.'
                errors.append({"error": error_msg})
                logger.warning(error_msg)
                return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)

            slug = slugify(name + str(timezone.now()))

            # Create the new Audience page
            audience_instance = Audience(
                title=name,
                slug=slug,
                audience_id=audience_id,
                name=name,
                key=key,
                description=description or "",
            )

            try:
                # Add as child page under the parent page
                parent_page.add_child(instance=audience_instance)
                audience_instance.save()
                created_entries.append(AudienceSerializer(audience_instance).data)
                logger.info(f"Audience entry '{name}' created successfully.")
            except ValidationError as e:
                errors.append(
                    {
                        "error": f"Validation error for entry '{name}': {str(e)}, at index : {index}"
                    }
                )
                logger.error(
                    f"Validation error for entry '{name}': {str(e)}, at index : {index}"
                )
            except Exception as e:
                errors.append(
                    {
                        "error": f"Failed to create entry '{name}': {str(e)}, at index : {index}"
                    }
                )
                logger.error(
                    f"Failed to create audience entry '{name}': {str(e)}, at index : {index}"
                )

        if created_entries:
            return Response(
                {"created": created_entries, "errors": errors},
                status=status.HTTP_201_CREATED,
            )
        else:
            return Response({"errors": errors}, status=status.HTTP_400_BAD_REQUEST)


class AudienceBulkDeleteViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request, *args, **kwargs):
        try:
            # Retrieve all Audience entries
            entries = Audience.objects.all()

            if not entries.exists():
                return Response(
                    {"message": "No entries found to delete."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            # Delete all entries
            count = entries.delete()

            logger.info(f"Deleted all Audience entries successfully. Count: {count}")
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


class AudienceNameCheckViewSet(viewsets.ViewSet):
    """
    API endpoint to check the uniqueness of a given audience name.
    The client sends a GET request with a query parameter `audience_name`,
    and the endpoint returns a JSON response indicating if the name is unique.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    @action(detail=False, methods=["get"], url_path="check")
    def check_audience_name(self, request):
        audience_name = request.query_params.get("audience_name")
        if not audience_name:
            return Response(
                {"error": "The query parameter 'audience_name' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check case-insensitively if a audience with the same name already exists.
        exists = Audience.objects.filter(name__iexact=audience_name).exists()
        return Response({"unique": not exists}, status=status.HTTP_200_OK)


#
