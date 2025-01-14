import uuid

from core.users.permissions import IsAdminOrRegisteredUser
from core.utils.custom_token_authentication import CustomTokenAuthentication
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page

from .enums import PersonaPermission
from .models import Role
from .serializers import RoleSerializer


class RoleViewSet(viewsets.ModelViewSet):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminOrRegisteredUser]
    queryset = Role.objects.all()
    serializer_class = RoleSerializer

    def create(self, request, *args, **kwargs):
        data = request.data
        names = data.get("names")

        if not names or not isinstance(names, list):
            return Response(
                {"error": "A list of names is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        roles = []
        parent_page = self._get_or_create_parent_page()

        for item in names:
            name = item.get("name")
            # Use provided role_id or generate a new one
            role_id = item.get("role_id", str(uuid.uuid4()))
            permissions = item.get("permissions", [])

            if not name:
                return Response(
                    {"error": "Each name must have a valid name field."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            role_data = {
                "title": name,
                "slug": slugify(name),
                "role_id": role_id,
                "name": name,
                "permissions": permissions,
                # might be using this part of code in a later part of development
                # "permissions": (
                #     PersonaPermission[name].value
                #     if name in PersonaPermission.__members__
                #     else []
                # ),
            }

            role_instance = Role(**role_data)

            # Manually set the path and depth if it's the first child
            if not parent_page.get_children().exists():
                role_instance.depth = parent_page.depth + 1
                role_instance.path = parent_page.path + "0001"
                role_instance.numchild = 0
                role_instance.save()
                parent_page.numchild += 1
                parent_page.save()
            else:
                parent_page.add_child(instance=role_instance)

            # Final save to ensure everything is committed
            role_instance.save()

            roles.append(role_instance)

        serializer = self.get_serializer(roles, many=True)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        role = self.get_object()
        serializer = self.get_serializer(role, data=request.data, partial=True)
        if serializer.is_valid():
            name = request.data.get("name", role.name)
            if name in PersonaPermission.__members__:
                serializer.validated_data["permissions"] = PersonaPermission[name].value

            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=["delete"], url_path="bulk-delete")
    def bulk_delete(self, request, *args, **kwargs):
        role_ids = request.data.get("role_ids", [])

        if not role_ids or not isinstance(role_ids, list):
            return Response(
                {"error": "A list of role IDs is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        roles = Role.objects.filter(role_id__in=role_ids)

        if not roles.exists():
            return Response(
                {"error": "No roles found with the provided IDs"},
                status=status.HTTP_404_NOT_FOUND,
            )

        deleted_count = roles.delete()
        return Response(
            {"message": f"Successfully deleted {deleted_count} roles."},
            status=status.HTTP_204_NO_CONTENT,
        )

    def list(self, request, *args, **kwargs):
        """
        Retrieve all roles in the system.
        """
        roles = self.get_queryset()
        serializer = self.get_serializer(roles, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def _get_or_create_parent_page(self):
        try:
            parent_page = Page.objects.get(slug="roles")
        except Page.DoesNotExist:
            root_page = Page.objects.first()
            parent_page = Page(
                title="Roles",
                slug="roles",
            )
            root_page.add_child(instance=parent_page)
            root_page.save()
        return parent_page
