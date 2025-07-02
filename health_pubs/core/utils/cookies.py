from django.conf import settings


def set_refresh_token_cookie(response, token):
    """
    Attach the refresh-token cookie with flags based on DEBUG:
      - DEBUG=True (dev):  SameSite=None, Secure=False
      - DEBUG=False (prod): SameSite=Lax,  Secure=True
    """
    secure = not settings.DEBUG
    samesite = "None" if settings.DEBUG else "Lax"

    response.set_cookie(
        key="long_term_token",
        value=token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=settings.REFRESH_TOKEN_MAX_AGE,
    )
    return response
