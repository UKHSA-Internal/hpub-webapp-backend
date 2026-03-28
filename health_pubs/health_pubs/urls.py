from django.contrib import admin
from django.urls import include, path

API_PREFIX = "api/v1/"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("core.self.urls")),
    path("", include("core.auth.urls")),
    path(f"{API_PREFIX}", include("core.event_analytics.urls")),
    path("", include("core.users.urls")),
    path(f"{API_PREFIX}products/", include("core.products.urls")),
    path("", include("core.roles.urls")),
    path(f"{API_PREFIX}", include("core.orders.urls")),
    path("", include("core.programs.urls")),
    path("", include("core.addresses.urls")),
    path("", include("core.organizations.urls")),
    path("", include("core.establishments.urls")),
    path(f"{API_PREFIX}", include("core.order_limits.urls")),
    path(f"{API_PREFIX}", include("core.feedbacks.urls")),
    path(f"{API_PREFIX}", include("core.audiences.urls")),
    path(f"{API_PREFIX}", include("core.diseases.urls")),
    path(f"{API_PREFIX}", include("core.vaccinations.urls")),
    path(f"{API_PREFIX}", include("core.customer_support.urls")),
    path(f"{API_PREFIX}", include("core.languages.urls")),
    path(f"{API_PREFIX}", include("core.where_to_use.urls")),
    path(f"{API_PREFIX}", include("core.frontend_s3_presigned_url.urls")),
    path("api/v2/", include("core.notifications.urls")),
    path("api/v2/", include("core.analytics.urls")),
]
