from django.urls import path

from .views import AnalyticsCsvView, AnalyticsDatasetView, AnalyticsMetadataView

urlpatterns = [
    path("analytics/", AnalyticsDatasetView.as_view(), name="analytics_dataset"),
    path("analytics/data.csv", AnalyticsCsvView.as_view(), name="analytics_data_csv"),
    path(
        "analytics/metadata.json",
        AnalyticsMetadataView.as_view(),
        name="analytics_metadata",
    ),
]
