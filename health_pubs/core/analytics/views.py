import csv

from core.users.permissions import IsAdminUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.conf import settings
from django.db.models import Count, Max, Min
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from rest_framework import status
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from .models import AnalyticsKPI
from .serializers import AnalyticsKPISerializer


class AnalyticsDatasetView(APIView):
    """Provides dataset summary and discoverable links to CSV and metadata endpoints."""

    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        summary = AnalyticsKPI.objects.aggregate(
            row_count=Count("kpi_id"),
            latest_year=Max("year"),
        )

        latest_year = summary["latest_year"]
        latest_month = None
        if latest_year is not None:
            latest_month = (
                AnalyticsKPI.objects.filter(year=latest_year).aggregate(latest=Max("month"))["latest"]
            )

        return JsonResponse(
            {
                "name": "HPUB KPI dataset",
                "description": "Dataset presenting monthly performance metrics for the Find Public Health Resources service. The KPIs track user satisfaction, order completion rate, digital take up and cost per transaction. Data is sourced from service analytics platforms including Power BI and Google Analytics.",
                "csv_url": request.build_absolute_uri(reverse("analytics_data_csv")),
                "metadata_url": request.build_absolute_uri(reverse("analytics_metadata")),
                "row_count": summary["row_count"],
                "latest_year": latest_year,
                "latest_month": latest_month,
            },
            status=status.HTTP_200_OK,
        )


class AnalyticsCsvView(APIView):
    """Serves public KPI CSV on GET and allows admin upsert KPI rows on POST."""

    authentication_classes = [SessionAuthentication, CustomTokenAuthentication]

    def get_permissions(self):
        if self.request.method == "GET":
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAuthenticated, IsAdminUser]
        return [permission() for permission in permission_classes]

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'inline; filename="HPUB_analytics_kpi_data.csv"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "Year",
                "Month",
                "User Satisfaction Score",
                "Digital Take-up",
                "Cost per Transaction",
                "Order Completion Rate",
            ]
        )

        for item in AnalyticsKPI.objects.all().order_by("year", "month"):
            writer.writerow(
                [
                    item.year,
                    item.month,
                    item.user_satisfaction_score,
                    item.digital_take_up_percentage,
                    item.cost_per_transaction,
                    item.order_completion_rate_percentage,
                ]
            )

        return response

    def post(self, request, *args, **kwargs):
        payload = request.data.copy()

        year = payload.get("year")
        month = payload.get("month")

        try:
            year = int(year)
            month = int(month)
        except (TypeError, ValueError):
            return JsonResponse(
                {
                    "error": "year and month are required and must be integers (for example year=2026, month=2)."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if month < 1 or month > 12:
            return JsonResponse(
                {"error": "month must be between 1 and 12."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        required_metric_fields = [
            "user_satisfaction_score",
            "digital_take_up_percentage",
            "cost_per_transaction",
            "order_completion_rate_percentage",
        ]

        submitted_metrics = {}
        missing_fields = []
        for field_name in required_metric_fields:
            value = payload.get(field_name)
            if value is None or str(value).strip() == "":
                missing_fields.append(field_name)
            else:
                submitted_metrics[field_name] = str(value).strip()

        if missing_fields:
            return JsonResponse(
                {
                    "error": "Missing required metric fields.",
                    "missing_fields": missing_fields,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Use POST as an upsert by business key (year+month), so admins do not need to look up kpi_id for updates.
        existing = AnalyticsKPI.objects.filter(year=year, month=month).first()
        serializer = AnalyticsKPISerializer(
            instance=existing,
            data={
                "year": year,
                "month": month,
                **submitted_metrics,
            },
        )
        serializer.is_valid(raise_exception=True)
        kpi = serializer.save()

        status_code = status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        return JsonResponse(
            AnalyticsKPISerializer(kpi).data,
            status=status_code,
        )


class AnalyticsMetadataView(APIView):
    """Returns DCAT-style metadata used by external harvester data.gov.uk."""

    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        dates = AnalyticsKPI.objects.aggregate(
            issued=Min("created_at"),
            modified=Max("updated_at"),
        )

        issued_date = (
            dates["issued"].date().isoformat()
            if dates["issued"]
            else timezone.now().date().isoformat()
        )
        modified_date = (
            dates["modified"].date().isoformat()
            if dates["modified"]
            else issued_date
        )

        metadata = {
            "accessLevel": "public",
            "landingPage": getattr(settings, "HPUB_FRONT_END_URL", ""),
            "issued": issued_date,
            "@type": "dcat:Dataset",
            "modified": modified_date,
            "keyword": [
                "health",
                "resources",
                "vaccinations",
                "diseases",
                "pandemic",
                "videos",
                "posters",
                "stickers",
                "public health",
                "health care",
            ],
            "contactPoint": {
                "@type": "vcard:Contact",
                "fn": "Find Public Health Resources",
                "hasEmail": "mailto:no-reply.publichealthresources@ukhsa.gov.uk",
            },
            "publisher": {
                "@type": "org:Organization",
                "name": "UK Health Security Agency",
            },
            "identifier": request.build_absolute_uri(reverse("analytics_metadata")),
            "description": "Dataset presenting monthly performance metrics for the Find Public Health Resources service. The KPIs track user satisfaction, order completion rate, digital take up and cost per transaction. Data is sourced from service analytics platforms including Power BI and Google Analytics.",
            "title": "Find Public Health Resources",
            "distribution": [
                {
                    "@type": "dcat:Distribution",
                    "downloadURL": request.build_absolute_uri(
                        reverse("analytics_data_csv")
                    ),
                    "mediaType": "text/csv",
                }
            ],
            "license": (
                "http://www.nationalarchives.gov.uk/doc/open-government-licence/"
                "version/3/"
            ),
            "theme": ["Health"],
        }

        return JsonResponse(metadata, status=status.HTTP_200_OK)
