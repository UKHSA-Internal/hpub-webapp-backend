from __future__ import annotations
from typing import Type
from rest_framework import viewsets, filters, permissions
from django_filters.rest_framework import DjangoFilterBackend

from ..models import User
from ..serializers import UserSerializer
from .views import CustomPagination

class UsersV2(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["email"]
    search_fields = ["email"]
    pagination_class = CustomPagination

