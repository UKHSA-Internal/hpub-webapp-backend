from django.urls import path
from . import views

urlpatterns = [
    path("api/v2/auth/decode/", views.get_token),
    path("api/v2/auth/users/", views.get_user),
    path("api/v2/auth/token/", views.create_access_token),
    path("api/v2/auth/refresh/", views.refresh_access_token),
    path("api/v2/auth/revoke/", views.revoke_access_token),
]
