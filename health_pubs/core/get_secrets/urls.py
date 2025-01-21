from django.urls import path
from .views import get_frontend_secrets

urlpatterns = [
    path("frontend-secrets/", get_frontend_secrets, name="frontend_secrets"),
]
