from django.http import JsonResponse


def handle_error(error_code, error_message, status_code=400) -> JsonResponse:
    """
    Generate a standardized error response.

    Args:
        error_code (ErrorCode): The error code Enum.
        error_message (ErrorMessage): The error message Enum.
        status_code (int): The HTTP status code.

    Returns:
        JsonResponse: The error response.
    """
    return JsonResponse(
        {
            "error_code": str(error_code),  # Relies on __str__ from the Enum
            "error_message": str(error_message),  # Relies on __str__ from the Enum
        },
        status=status_code,
    )
