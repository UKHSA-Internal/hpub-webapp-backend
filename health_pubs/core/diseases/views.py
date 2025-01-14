import logging
import uuid

from core.programs.models import Program
from core.users.permissions import IsAdminOrRegisteredUser, IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page

from .models import Disease
from .serializers import DiseaseSerializer

logger = logging.getLogger(__name__)


class DiseaseCreateViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    queryset = Disease.objects.all()
    serializer_class = DiseaseSerializer

    def create(self, request, *args, **kwargs):
        data = request.data
        # Check if we are dealing with a single disease or multiple diseases
        if isinstance(data, dict) and "diseases" in data:
            items_data = data.pop("diseases", [])
        else:
            items_data = [data]  # Treat as a single disease instance

        logger.info(f"Request Data: {data}")

        # Retrieve or create the parent page
        parent_page = self._get_or_create_parent_page_or_error()

        disease_instances = []
        errors = []

        for disease_data in items_data:
            disease_instance = self._create_disease_page(disease_data, parent_page)
            if isinstance(disease_instance, dict) and "error" in disease_instance:
                errors.append(disease_instance)  # Collect errors
            else:
                disease_instances.append(disease_instance)

        # If there are any errors, return the first one with the corresponding status code
        if errors:
            return Response(
                errors, status=errors[0].get("status_code", status.HTTP_400_BAD_REQUEST)
            )

        return Response(disease_instances, status=status.HTTP_201_CREATED)

    def _create_disease_page(self, disease_data, parent_page_slug="diseases"):
        logger.info("DISEASE DATA: %s", disease_data)

        # Validate required fields
        required_fields = ["name", "program_names"]  # Update to program_names
        for field in required_fields:
            if field not in disease_data:
                logger.error(f"Missing required field: {field}")
                return {
                    "error": f"Missing required field: {field}",
                    "status_code": status.HTTP_400_BAD_REQUEST,
                }

        title = disease_data.get("name", "Disease Title")
        slug = slugify(f"{title}-{uuid.uuid4()}")

        # Handle the program association
        program_names = disease_data.get("program_names", [])
        program_refs = []
        for program_name in program_names:
            try:
                program_ref = Program.objects.get(programme_name=program_name)
                program_refs.append(program_ref)
                logger.info(f"Program '{program_name}' found.")
            except Program.DoesNotExist:
                logger.warning(f"Program '{program_name}' does not exist.")
                return {
                    "error": f"Program '{program_name}' does not exist.",
                    "status_code": status.HTTP_404_NOT_FOUND,
                }

        # Ensure parent page exists or create it if necessary
        parent_page = self._get_or_create_parent_page(parent_page_slug)

        # Check if a disease with the same name already exists
        existing_disease = Disease.objects.filter(name=title).first()
        if existing_disease:
            logger.error(f"Disease with name '{title}' already exists.")
            return {
                "error": f"Disease with name '{title}' already exists.",
                "status_code": status.HTTP_400_BAD_REQUEST,
            }

        # Create the new Disease page since it doesn't exist
        disease_page = Disease(
            title=title,
            slug=slug,
            name=title,
            disease_id=disease_data.get("disease_id", str(uuid.uuid4())),
            key=disease_data.get("key", ""),
            description=disease_data.get("description", ""),
        )

        # Use add_child() to associate the new page with the parent page
        parent_page.add_child(instance=disease_page)
        disease_page.save()  # Save the disease page to persist it in the database

        # Associate the disease with programs
        disease_page.programs.set(program_refs)  # Many-to-many association
        disease_page.save()

        logger.info(
            f"Disease page '{title}' created under parent '{parent_page.title}'."
        )

        logger.info(f"Disease '{title}' instance created successfully.")
        return DiseaseSerializer(disease_page).data

    def _get_or_create_parent_page(self, slug="diseases"):
        try:
            parent_page = Page.objects.get(slug=slug)
            logger.info(f"Parent page '{slug}' found.")
        except Page.DoesNotExist:
            logger.warning(f"Parent page '{slug}' not found, creating a new one.")
            root_page = Page.objects.first()  # Adjust as necessary
            if root_page is None:
                logger.error("No root page exists, cannot create a new parent page.")
                raise Exception("Root page not found.")
            parent_page = Page(title="Diseases", slug=slug)
            root_page.add_child(instance=parent_page)
            parent_page.save()  # Save the parent page
            logger.info(f"Parent page '{slug}' created.")
        return parent_page

    def _get_or_create_parent_page_or_error(self):
        try:
            return self._get_or_create_parent_page()
        except Exception:
            logger.exception("Error creating or retrieving parent page for diseases.")
            raise ValidationError(
                {"error": "Error creating or retrieving parent page."}
            )


class DiseaseListViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    queryset = Disease.objects.all()
    serializer_class = DiseaseSerializer

    def list(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DiseaseDeleteAllViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["delete"], url_path="delete-all")
    def delete_all(self, request, *args, **kwargs):
        try:
            # Delete all Disease records
            count = Disease.objects.all().delete()
            logger.info(f"Deleted {count} disease(s).")
            return Response(
                {"message": f"Successfully deleted {count} disease(s)."},
                status=status.HTTP_204_NO_CONTENT,
            )
        except Exception as e:
            logger.error(f"Error deleting diseases: {str(e)}")
            return Response(
                {"error": "Failed to delete all diseases."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


#
