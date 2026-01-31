from django.urls import path
from .views import get_access_token

urlpatterns = [
    path('api/v2/auth/token/', get_access_token, name='auth'),
]