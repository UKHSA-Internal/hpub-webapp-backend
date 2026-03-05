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
            latest_period=Max("period"),
        )

        latest_period = summary["latest_period"]
        return JsonResponse(
            {
                "name": "Find Public Health Resources KPI Dataset",
                "description": "Monthly KPI dataset for data.gov.uk harvesting.",
                "csv_url": request.build_absolute_uri(
                    reverse("analytics_data_csv")
                ),
                "metadata_url": request.build_absolute_uri(
                    reverse("analytics_metadata")
                ),
                "row_count": summary["row_count"],
                "latest_period": latest_period.isoformat() if latest_period else None,
            },
            status=status.HTTP_200_OK,
        )


class AnalyticsCsvView(APIView):
    """Serves public KPI CSV on GET and allows admin update/insert KPI rows on POST."""
    authentication_classes = [SessionAuthentication, CustomTokenAuthentication]

    def get_permissions(self):
        if self.request.method == "GET":
            permission_classes = [AllowAny]
        else:
            permission_classes = [IsAuthenticated, IsAdminUser]
        return [permission() for permission in permission_classes]

    def get(self, request, *args, **kwargs):
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = 'inline; filename="analytics_kpi_data.csv"'

        writer = csv.writer(response)
        writer.writerow(
            [
                "period",
                "website_visits_sum",
                "feedback_form_submissions",
            ]
        )

        for item in AnalyticsKPI.objects.all().order_by("period"):
            writer.writerow(
                [
                    item.period.isoformat(),
                    item.website_visits_sum,
                    item.feedback_form_submissions,
                ]
            )

        return response

    def post(self, request, *args, **kwargs):
        period = request.data.get("period")
        if not period:
            return JsonResponse(
                {"error": "period is required (YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        existing = AnalyticsKPI.objects.filter(period=period).first()
        serializer = AnalyticsKPISerializer(instance=existing, data=request.data)
        serializer.is_valid(raise_exception=True)
        kpi = serializer.save()

        status_code = (
            status.HTTP_200_OK if existing else status.HTTP_201_CREATED
        )
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
            "keyword": ["kpi", "website", "feedback"],
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
            "description": (
                "Monthly KPI data for HPUB service performance, including website "
                "visits and submitted feedback forms."
            ),
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
