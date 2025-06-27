from django.conf import settings

# How long the refresh token cookie lives, in seconds:
REFRESH_TOKEN_MAX_AGE = settings.REFRESH_TOKEN_MAX_AGE


def set_refresh_token_cookie(response, token):
    """
    Attach a long-term (refresh) token cookie to the given HttpResponse,
    choosing Secure/SameSite flags based on DEBUG.
    """
    # In DEBUG (dev on HTTP) we cannot use Secure=True with SameSite=None,
    # so we use Lax. In production we allow cross-site (None) but must be Secure.
    secure = not settings.DEBUG
    samesite = "Lax" if settings.DEBUG else "None"

    response.set_cookie(
        key="long_term_token",
        value=token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=REFRESH_TOKEN_MAX_AGE,
    )
    return response
