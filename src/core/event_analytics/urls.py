from django.urls import path
from .views import (
    EventAnalyticsCreateView,
    EventAnalyticsAdminListView,
    EventAnalyticsStatsView,
    EventAnalyticsStatsViewPerSessionId,
)

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
    path(
        "event-analytics/stats/",
        EventAnalyticsStatsView.as_view(),
        name="event_analytics_stats",
    ),
    path(
        "event-analytics/stats/session-id/",
        EventAnalyticsStatsViewPerSessionId.as_view(),
        name="event_analytics_stats_session_id",
    ),
]
