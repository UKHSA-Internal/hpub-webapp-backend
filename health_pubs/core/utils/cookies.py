from django.conf import settings

def set_refresh_token_cookie(response, token):
    """
    Attach the refresh-token cookie. In dev we use SameSite=Lax so it isn't
    rejected over HTTP. In prod we use SameSite=None+Secure so it works
    cross-site over HTTPS.
    """
    secure = not settings.DEBUG
    samesite = "None" if secure else "Lax"

    response.set_cookie(
        key="long_term_token",
        value=token,
        httponly=True,
        secure=secure,
        samesite=samesite,
        max_age=settings.REFRESH_TOKEN_MAX_AGE,
        path="/",
    )
    return response
