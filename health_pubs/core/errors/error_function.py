from django.http import JsonResponse


def handle_error(error_code, error_message, status_code=400):
    print(error_code, error_message)
    return JsonResponse(
        {
            "error_code": str(error_code),  # Relies on __str__ from the Enum
            "error_message": str(error_message),  # Relies on __str__ from the Enum
        },
        status=status_code,
    )
