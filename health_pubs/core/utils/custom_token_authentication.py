import logging

import jwt
from core.users.models import User
from core.utils.token_generation_validation import (
    validate_token,
    validate_token_refresh,
)
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed

logger = logging.getLogger(__name__)


class CustomTokenAuthentication(BaseAuthentication):
    def authenticate(self, request):
        # For debugging purposes
        logger.info("Starting Token Authentication.....")
        from core.users.views import validate_azure_b2c_token

        # Get the Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            logger.error("Authorization header missing")
            return None

        # Extract the token
        token = auth_header.split(" ")[1] if " " in auth_header else None
        if not token:
            logger.error("Token missing in Authorization header")
            raise AuthenticationFailed("Token missing in Authorization header")

        try:
            # Decode token without validation to inspect claims
            unverified_payload = jwt.decode(
                token, options={"verify_signature": False, "verify_aud": False}
            )
            logger.info(
                "unverified_payload: %s", unverified_payload
            )  # For debugging purposes

            # Check if it's an Azure B2C token by looking for known claims
            if "iss" in unverified_payload:
                # Validate as Azure B2C token
                # For debugging purposes
                logger.info("Detected Azure B2C token")
                payload = validate_azure_b2c_token(token)
                # logger.info("Payload", payload) # For debugging purposes
                user = User.objects.filter(email=payload.get("email_address")).first()
                logger.info(
                    f"Authenticated user with refresh token: {user}"
                )  # For debugging purposes
                if user:
                    return (user, None)
                logger.warning("Azure B2C token valid but user does not exist")
                return None

            # Handle custom token types
            token_type = unverified_payload.get("type")
            if token_type == "access":
                # Validate as an access token
                payload = validate_token(token, token_type=token_type)
                user = User.objects.filter(user_id=payload["user_id"]).first()
                if user:
                    return (user, None)
                logger.warning("Access token valid but user does not exist")
                return None
            elif token_type == "refresh":
                # Validate as a refresh token
                payload = validate_token_refresh(token, token_type=token_type)
                user = User.objects.filter(user_id=payload["user_id"]).first()
                logger.info(
                    f"Authenticated user with access token: {user}"
                )  # For debugging purposes
                logger.info(
                    f"Authenticated user with refresh token: {user}"
                )  # For debugging purposes
                if user:
                    return (user, None)
                logger.warning("Refresh token valid but user does not exist")
                return None
            else:
                logger.info("Invalid or missing token type")
                return None

        except jwt.ExpiredSignatureError:
            raise AuthenticationFailed("Token has expired")
        except jwt.DecodeError:
            raise AuthenticationFailed("Invalid token")
        except User.DoesNotExist:
            raise AuthenticationFailed("User does not exist")
        except ValueError as e:
            logger.error(f"Authentication error: {e}")
            raise AuthenticationFailed(str(e))
