from django.urls import path
from .views import EventAnalyticsCreateView, EventAnalyticsAdminListView

urlpatterns = [
    path(
        "event-analytics/create/",
        EventAnalyticsCreateView.as_view(),
        name="event_analytics_create",
    ),
    path(
        "event-analytics/list/",
        EventAnalyticsAdminListView.as_view(),
        name="event_analytics_list",
    ),
]
