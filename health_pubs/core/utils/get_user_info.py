from core.users.serializers import UserSerializer


def get_user_info(obj, request=None):
    """
    Returns the serialized user information if the requesting user's role is 'admin'.
    Otherwise, it returns None.

    Parameters:
    - obj: an object that contains a `user_ref` attribute (or similar)
    - request: a Django HttpRequest object (optional). If not provided or invalid,
      the function will return None.

    Returns:
    - A dictionary containing serialized user data if the request is authenticated
      and the user role is admin, else None.
    """
    if request is None:
        return None

    user = getattr(request, "user", None)
    if not user:
        return None

    # Check that user has a role reference and that its name is 'admin'.
    rol_ref = getattr(user, "rol_ref", None)
    if rol_ref and hasattr(rol_ref, "name") and rol_ref.name.lower() == "admin":
        return UserSerializer(obj.user_ref).data

    return None
