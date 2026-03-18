# core/utils/custom_token_authentication.py

import logging
import jwt

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

from core.users.models import User
from core.utils.token_generation_validation import (
    validate_token,
    validate_token_refresh,
)

logger = logging.getLogger(__name__)


class CustomTokenAuthentication(BaseAuthentication):
    """
    Supports:
      1) Azure B2C tokens (with an 'iss' claim)
      2) Custom 'access' and 'refresh' tokens (with a 'type' claim)

    Looks first in Authorization header, then in 'long_term_token' cookie.
    """

    def authenticate(self, request):
        # Prevent double-attempt
        if getattr(self, "_attempted", False):
            logger.debug("Already attempted authentication")
            return None
        self._attempted = True

        token = self._get_token(request)
        if not token:
            logger.info("No token provided; skipping")
            return None

        # Peek inside without verifying signature
        try:
            unverified = jwt.decode(
                token, options={"verify_signature": False, "verify_aud": False}
            )
        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            raise AuthenticationFailed("Token expired")
        except jwt.DecodeError:
            logger.warning("Malformed token")
            raise AuthenticationFailed("Invalid token")
        except Exception:
            logger.exception("Unexpected decode error")
            return None

        # Azure B2C flow
        if "iss" in unverified:
            logger.debug("Detected Azure B2C token")
            from core.users.views import (
                validate_azure_b2c_token,
            )  # avoid circular import

            try:
                payload = validate_azure_b2c_token(token)
            except Exception:
                logger.warning("Azure B2C validation failed")
                raise AuthenticationFailed("Invalid Azure token")

            email = payload.get("email_address") or payload.get("email")
            user = User.objects.filter(email__iexact=email).first()
            if not user:
                logger.info("Azure B2C user not found: %s", email)
                return None

            # logger.info("Authenticated Azure B2C user %s", email) #for debugging
            return (user, None)

        # Custom tokens
        token_type = unverified.get("type")
        if token_type not in ("access", "refresh"):
            logger.info("Unknown token type: %s", token_type)
            return None

        try:
            if token_type == "access":
                payload = validate_token(token, token_type="access")
            else:
                payload = validate_token_refresh(token, token_type="refresh")
        except jwt.ExpiredSignatureError:
            logger.warning("%s token expired", token_type)
            raise AuthenticationFailed("Token expired")
        except Exception:
            logger.warning("%s token invalid", token_type)
            raise AuthenticationFailed("Invalid token")

        user_id = payload.get("user_id")
        user = (
            User.objects.filter(user_id=user_id).first()
            or User.objects.filter(pk=user_id).first()
        )
        if not user:
            logger.info("No user for token user_id=%s", user_id)
            return None

        logger.info(
            "Authenticated user %s via %s token", user.email, token_type
        )  # for debugging
        return (user, None)

    def _get_token(self, request):
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth.split()[1]
        cookie = request.COOKIES.get("long_term_token")
        if cookie:
            logger.debug("Using long_term_token from cookie")
        return cookie
