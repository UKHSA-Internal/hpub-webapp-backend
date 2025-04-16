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

    def authenticate(self, request):
        logger.info("Starting token authentication.")

        token = self._get_token_from_request(request)
        if not token:
            logger.error("No token found in header or cookie.")
            return None

        try:
            # Decode the token without signature or audience validation to inspect claims.
            unverified_payload = jwt.decode(
                token, options={"verify_signature": False, "verify_aud": False}
            )
            logger.debug("Unverified token payload: %s", unverified_payload)

            # If the token contains an issuer claim, we assume it's an Azure B2C token.
            if "iss" in unverified_payload:
                logger.info("Detected Azure B2C token. Importing validator locally.")
                # Import here to avoid circular dependency.
                from core.users.views import validate_azure_b2c_token

                payload = validate_azure_b2c_token(token)
                email = payload.get("email_address")
                user = User.objects.filter(email=email).first()
                if user:
                    logger.info("Authenticated Azure B2C user: %s", user)
                    return (user, None)
                logger.warning(
                    "Azure B2C token valid but no matching user found for email: %s",
                    email,
                )
                return None

            # Handle custom token types based on the 'type' claim.
            token_type = unverified_payload.get("type")
            if token_type == "access":
                payload = validate_token(token, token_type=token_type)
                user = User.objects.filter(user_id=payload.get("user_id")).first()
                if user:
                    logger.info("Authenticated user with access token: %s", user)
                    return (user, None)
                logger.warning(
                    "Access token valid but no matching user found for user_id: %s",
                    payload.get("user_id"),
                )
                return None

            elif token_type == "refresh":
                payload = validate_token_refresh(token, token_type=token_type)
                user = User.objects.filter(user_id=payload.get("user_id")).first()
                if user:
                    logger.info("Authenticated user with refresh token: %s", user)
                    return (user, None)
                logger.warning(
                    "Refresh token valid but no matching user found for user_id: %s",
                    payload.get("user_id"),
                )
                return None

            else:
                logger.info("Invalid or missing token type in token claims.")
                return None

        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Token has expired")
        except jwt.DecodeError:
            raise AuthenticationFailed("Invalid token")
        except ValueError as e:
            logger.error("Authentication error: %s", e)
            raise AuthenticationFailed(str(e))

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
