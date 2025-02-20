from django.contrib import admin
from django.urls import include, path

API_PREFIX = "api/v1/"

urlpatterns = [
    path("admin/", admin.site.urls),
    path(f"{API_PREFIX}", include("core.urls")),
    path(f"{API_PREFIX}", include("core.users.urls")),
    path(f"{API_PREFIX}products/", include("core.products.urls")),
    path(f"{API_PREFIX}", include("core.roles.urls")),
    path(f"{API_PREFIX}", include("core.orders.urls")),
    path(f"{API_PREFIX}", include("core.programs.urls")),
    path(f"{API_PREFIX}", include("core.addresses.urls")),
    path(f"{API_PREFIX}", include("core.organizations.urls")),
    path(f"{API_PREFIX}", include("core.establishments.urls")),
    path(f"{API_PREFIX}", include("core.order_limits.urls")),
    path(f"{API_PREFIX}", include("core.feedbacks.urls")),
    path(f"{API_PREFIX}", include("core.audiences.urls")),
    path(f"{API_PREFIX}", include("core.diseases.urls")),
    path(f"{API_PREFIX}", include("core.vaccinations.urls")),
    path(f"{API_PREFIX}", include("core.customer_support.urls")),
    path(f"{API_PREFIX}", include("core.languages.urls")),
    path(f"{API_PREFIX}", include("core.where_to_use.urls")),
    path(f"{API_PREFIX}", include("core.get_secrets.urls")),
    path(f"{API_PREFIX}", include("core.frontend_s3_presigned_url.urls")),
]
