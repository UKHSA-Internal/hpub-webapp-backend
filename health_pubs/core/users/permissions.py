from rest_framework.permissions import BasePermission


class IsAdminUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and hasattr(request.user, "role_ref")
            and request.user.role_ref.name == "Admin"
        )


class IsRegisteredUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and hasattr(request.user, "role_ref")
            and request.user.role_ref.name == "User"
        )


class IsAdminOrRegisteredUser(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and request.user.role_ref is not None
            and request.user.role_ref.name in ["Admin", "User"]
        )
