from wagtail.models import Page
from rest_framework import viewsets, status, filters, views
from rest_framework import permissions
from rest_framework import authentication
from rest_framework.response import Response
from rest_framework.pagination import PageNumberPagination

from django.contrib.contenttypes.models import ContentType
from django_filters.rest_framework import DjangoFilterBackend

from core.users.serializers import UserSerializer
from core.users.models import User
from core.utils import logging_utils


logger = logging_utils.get_logger(__name__)

class CustomPagination(PageNumberPagination):
    from django.conf import settings

    page_size = getattr(
        settings, "USERS_LIST_PAGE_SIZE", 10
    )  # Set pagination to 10 items per page

    def get_paginated_response(self, data, status_code=200):
        response = Response(
            {
                "metadata": {
                    "total_count": self.page.paginator.count,
                    "page_size": self.page_size,
                    "page_number": self.page.number,
                    "next_page": self.get_next_link(),
                    "previous_page": self.get_previous_link(),
                },
                "data": data,
            },
            status=status_code,
        )
        return response


class UsersV2(viewsets.ModelViewSet):
    queryset = User.objects.all().specific()
    serializer_class = UserSerializer
    authentication_classes = [custom_token_authentication.CustomTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter,]
    filterset_fields = [
        "email",
        "first_name",
        "last_name",
        "role_ref",
        "organization_ref",
        "establishment_ref",
    ]
    search_fields = [
        "email",
        "first_name",
        "last_name",
    ]
    pagination_class = CustomPagination

    def get_or_create_parent_page(self):
        slug = 'users'
        title = 'Users'
        try:
            parent = Page.objects.get(slug=slug)
            logger.info(f"Parent page '{title}' found.")
        except Page.DoesNotExist:
            logger.warning(f"Parent page '{title}' not found, creating.")
            root = Page.objects.first()
            parent = Page(
                title=title,
                slug=slug,
                content_type=ContentType.objects.get_for_model(Page),
            )
            root.add_child(instance=parent)
            logger.info(f"Parent page '{title}' created.")
        return parent

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        parent = self.get_or_create_parent_page()
        user = serializer.to_model()

        parent.add_child(instance=user)
        user.save()
        user.refresh_from_db()

        return Response(
            UserSerializer(user).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        instance = self.get_object()

        serializer = self.get_serializer(
            instance,
            data=request.data,
            partial=kwargs.get("partial", False),
        )
        serializer.is_valid(raise_exception=True)

        for attr, value in serializer.validated_data.items():
            setattr(instance, attr, value)

        instance.save()
        instance.refresh_from_db()

        return Response(UserSerializer(instance).data)

    # ---------------------------
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
    

class UserRolesView(views.APIView):
    authentication_classes = [custom_token_authentication.CustomTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def put(self, request, user_id):
        return Response(
            {"detail": "Not implemented"},
            status=status.HTTP_501_NOT_IMPLEMENTED
        )


class UserStateView(views.APIView):
    authentication_classes = [custom_token_authentication.CustomTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def put(self, request, user_id):
        return Response(
            {"detail": "Not implemented"},
            status=status.HTTP_501_NOT_IMPLEMENTED
        )