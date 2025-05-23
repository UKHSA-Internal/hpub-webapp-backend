import logging
import uuid
import pandas as pd
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from core.programs.models import Program
from core.users.permissions import IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page

from .models import Vaccination
from .serializers import VaccinationSerializer

logger = logging.getLogger(__name__)


class VaccinationCreateViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    queryset = Vaccination.objects.all()
    serializer_class = VaccinationSerializer

    def create(self, request, *args, **kwargs):
        data = request.data

        if isinstance(data, dict) and "vaccinations" in data:
            items_data = data.pop("vaccinations", [])
        else:
            items_data = [data]

        parent_page = self._get_or_create_parent_page_or_error()
        vaccination_instances = []
        errors = []

        for vaccination_data in items_data:
            vaccination_instance = self._create_vaccination_page(
                vaccination_data, parent_page
            )
            if (
                isinstance(vaccination_instance, dict)
                and "error" in vaccination_instance
            ):
                errors.append(vaccination_instance)
            else:
                vaccination_instances.append(vaccination_instance)

        if errors:
            logger.error(f"Errors during vaccination creation: {errors}")
            return Response(
                errors, status=errors[0].get("status_code", status.HTTP_400_BAD_REQUEST)
            )

        return Response(vaccination_instances, status=status.HTTP_201_CREATED)

    def _create_vaccination_page(
        self, vaccination_data, parent_page_slug="vaccinations"
    ):
        title = vaccination_data.get("name", "Vaccination Title")
        slug = slugify(f"{title}-{uuid.uuid4()}")

        program_names = vaccination_data.get("program_names", [])
        program_refs = []
        for program_name in program_names:
            try:
                program_refs.append(Program.objects.get(programme_name=program_name))
            except Program.DoesNotExist:
                return {
                    "error": f"Program '{program_name}' does not exist.",
                    "status_code": status.HTTP_404_NOT_FOUND,
                }

        parent_page = self._get_or_create_parent_page(parent_page_slug)

        if Vaccination.objects.filter(name=title).exists():
            return {
                "error": f"Vaccination with name '{title}' already exists.",
                "status_code": status.HTTP_400_BAD_REQUEST,
            }

        vaccination_page = Vaccination(
            title=title,
            slug=slug,
            vaccination_id=vaccination_data.get("vaccination_id", str(uuid.uuid4())),
            name=vaccination_data.get("name"),
            key=vaccination_data.get("key", ""),
            description=vaccination_data.get("description", ""),
        )

        parent_page.add_child(instance=vaccination_page)
        vaccination_page.save()
        vaccination_page.programs.set(program_refs)
        vaccination_page.save()

        return VaccinationSerializer(vaccination_page).data

    def _get_or_create_parent_page(self, slug="vaccinations"):
        try:
            return Page.objects.get(slug=slug)
        except Page.DoesNotExist:
            root_page = Page.objects.first()
            parent_page = Page(title="Vaccinations", slug=slug)
            root_page.add_child(instance=parent_page)
            parent_page.save()
            return parent_page

    def _get_or_create_parent_page_or_error(self):
        try:
            return self._get_or_create_parent_page()
        except Exception:
            raise ValidationError({"error": "Error creating/retrieving parent page."})


class VaccinationListViewSet(viewsets.ReadOnlyModelViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    queryset = Vaccination.objects.all()
    serializer_class = VaccinationSerializer


class VaccinationDeleteViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def destroy(self, request, pk=None):
        try:
            vaccination = Vaccination.objects.get(pk=pk)
            vaccination.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Vaccination.DoesNotExist:
            return Response(
                {"error": "Vaccination not found."}, status=status.HTTP_404_NOT_FOUND
            )

    @action(detail=False, methods=["delete"], url_path="delete-all")
    def delete_all(self, request, *args, **kwargs):
        try:
            # Delete all Vaccination records
            count = Vaccination.objects.all().delete()
            logger.info(f"Deleted {count} vaccination(s).")
            return Response(
                {"message": f"Successfully deleted {count} vaccination(s)."},
                status=status.HTTP_204_NO_CONTENT,
            )
        except Exception as e:
            logger.error(f"Error deleting vaccinations: {str(e)}")
            return Response(
                {"error": "Failed to delete all vaccinations."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class VaccinationNameCheckViewSet(viewsets.ViewSet):
    """
    API endpoint to check the uniqueness of a given vaccination name.
    The client sends a GET request with a query parameter `vaccination_name`,
    and the endpoint returns a JSON response indicating if the name is unique.
    """

    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    @action(detail=False, methods=["get"], url_path="check")
    def check_vaccination_name(self, request):
        vaccination_name = request.query_params.get("vaccination_name")
        if not vaccination_name:
            return Response(
                {"error": "The query parameter 'vaccination_name' is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check case-insensitively if a vaccination with the same name already exists.
        exists = Vaccination.objects.filter(name__iexact=vaccination_name).exists()
        return Response({"unique": not exists}, status=status.HTTP_200_OK)


class VaccinationBulkUploadViewSet(viewsets.ViewSet):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    @action(detail=False, methods=["post"], url_path="bulk-upload")
    def bulk_upload(self, request):
        # 1. Load and validate the Excel
        df, error_resp = self._load_excel(request)
        if error_resp:
            return error_resp

        # 2. Ensure parent page exists
        parent_page = self._get_parent_page()

        # 3. Iterate rows
        created, errors = self._process_rows(df, parent_page)

        # 4. Return result
        return Response(
            {"created": created, "errors": errors}, status=201 if created else 400
        )

    def _load_excel(self, request):
        excel = request.FILES.get("excel_file")
        if not excel:
            return None, Response(
                {"error": "Excel file is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        name = excel.name.lower()
        if not name.endswith((".xlsx", ".xls")):
            return None, Response(
                {"error": "Upload a valid Excel file (.xlsx or .xls)"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            df = pd.read_excel(excel)
        except Exception as e:
            return None, Response(
                {"error": f"Failed to read Excel file: {e}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return df, None

    def _get_parent_page(self):
        try:
            return Page.objects.get(slug="vaccination-bulk")
        except Page.DoesNotExist:
            root = Page.objects.first()
            parent = Page(
                title="VaccinationBulk",
                slug="vaccination-bulk",
                content_type=ContentType.objects.get_for_model(Page),
            )
            root.add_child(instance=parent)
            return parent

    def _process_rows(self, df, parent_page):
        created, errors = [], []
        for idx, row in df.iterrows():
            data, err = self._process_row(idx, row, parent_page)
            if data:
                created.append(data)
            else:
                errors.append(err)
        return created, errors

    def _process_row(self, index, row, parent_page):
        vid = row.get("id")
        name = row.get("label")
        key = row.get("key")
        desc = row.get("description") or ""
        progs = row.get("program_names")

        # Required fields
        if pd.isna(vid) or pd.isna(name):
            return None, {"row": index + 1, "error": "Missing required fields"}

        # Duplicate check
        if Vaccination.objects.filter(vaccination_id=vid).exists():
            return None, {
                "row": index + 1,
                "error": f"Vaccination with ID {vid} already exists",
            }

        # Instantiate
        slug = slugify(f"{name}{timezone.now()}")
        vac = Vaccination(
            title=name,
            slug=slug,
            vaccination_id=vid,
            name=name,
            key=key,
            description=desc,
        )

        try:
            parent_page.add_child(instance=vac)
            vac.save()

            # M2M programs
            if pd.notna(progs):
                names = [p.strip() for p in progs.split(",")]
                queryset = Program.objects.filter(programme_name__in=names)
                vac.programs.set(queryset)

            return VaccinationSerializer(vac).data, None

        except Exception as e:
            return None, {"row": index + 1, "error": str(e)}


#
