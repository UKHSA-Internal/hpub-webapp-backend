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
    Custom token authentication that supports multiple token types.

    The class first attempts to retrieve the token from the Authorization header.
    If no header token is found, it looks for a token in a cookie (for example, "long_term_token").
    The token is decoded without verifying its signature to inspect claims.
    Depending on the presence of an "iss" claim or the custom "type" claim, the token is validated
    with the appropriate helper.
    """

    def __init__(self):
        self._authentication_attempted = False

    def authenticate(self, request):
        # 1) Ensure single attempt
        if self._authentication_attempted:
            logger.debug("Authentication already attempted")
            return None
        self._authentication_attempted = True

        logger.debug("Starting token authentication")

        # 2) Retrieve token
        token = self._get_token_from_request(request)
        if not token:
            logger.info("No token provided")
            return None

        # 3) Decode unverified to inspect type/issuer
        try:
            unverified = jwt.decode(
                token, options={"verify_signature": False, "verify_aud": False}
            )
        except jwt.ExpiredSignatureError:
            logger.warning("Token expired")
            raise AuthenticationFailed("Token has expired")
        except jwt.DecodeError:
            logger.warning("Token decode error")
            raise AuthenticationFailed("Invalid token format")
        except Exception:
            logger.error("Unexpected error decoding token")
            return None

        # 4) Azure B2C token
        if "iss" in unverified:
            logger.debug("Azure B2C token detected")
            from core.users.views import (
                validate_azure_b2c_token,
            )  # avoid circular import

            try:
                payload = validate_azure_b2c_token(token)
            except Exception:
                logger.warning("Azure B2C validation failed")
                raise AuthenticationFailed("Invalid Azure B2C token")

            email = payload.get("email_address")
            user = User.objects.filter(email=email).first()
            if not user:
                logger.info("Azure B2C user not found")
                return None

            logger.info("Azure B2C user authenticated")
            return (user, None)

        # 5) Custom access / refresh tokens
        token_type = unverified.get("type")
        if token_type not in ("access", "refresh"):
            logger.info("Unsupported token type")
            return None

        try:
            if token_type == "access":
                payload = validate_token(token, token_type=token_type)
            else:  # refresh
                payload = validate_token_refresh(token, token_type=token_type)
        except jwt.ExpiredSignatureError:
            logger.warning("%s token expired", token_type.capitalize())
            raise AuthenticationFailed("Token has expired")
        except Exception:
            logger.warning("%s token validation failed", token_type.capitalize())
            raise AuthenticationFailed("Invalid token")

        # 6) Lookup user by ID
        user_id = payload.get("user_id")
        user = (
            User.objects.filter(user_id=user_id).first()
            or User.objects.filter(pk=user_id).first()
        )
        if not user:
            logger.info("User not found for provided token")
            return None

        logger.info("User authenticated via %s token", token_type)
        return (user, None)

    def _get_token_from_request(self, request):
        """
        Attempts to retrieve a token from the Authorization header first,
        and falls back to the "long_term_token" cookie.
        """
        auth_header = request.headers.get("Authorization")
        if auth_header:
            parts = auth_header.split(" ")
            if len(parts) == 2:
                logger.info("Token found in Authorization header.")
                return parts[1]
            else:
                logger.error("Authorization header is improperly formatted.")

        # Fallback: try to retrieve token from cookies.
        token = request.COOKIES.get("long_term_token")
        if token:
            logger.info("Token found in cookies.")
        return token
