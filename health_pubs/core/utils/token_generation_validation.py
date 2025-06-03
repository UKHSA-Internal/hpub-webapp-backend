from datetime import timedelta
import uuid

import jwt
from core.users.models import InvalidatedToken
from django.conf import settings
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)


def validate_token(token, token_type="access", user=None):
    """Validates token based on type and expiration."""
    # Check if the token has been invalidated for this user
    prefix = token[:10]
    if user and InvalidatedToken.objects.filter(token=token, user=user).exists():
        logger.error("Token %s already invalidated for user %s", prefix, user.email)
        raise ValueError("Token has been invalidated for this user")

    try:
        logger.debug("Validating %s-token %s...", token_type, prefix)
        payload = jwt.decode(token, settings.PUBLIC_KEY, algorithms=["RS256"])
        if payload["type"] != token_type:
            logger.error("Token %s has wrong type %s", prefix, payload.get("type"))
            raise ValueError("Incorrect token type")
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.DecodeError:
        raise ValueError("Invalid token")


def validate_token_refresh(token, token_type="refresh", user=None):
    """Validates token based on type and expiration."""
    # Check if the token has been invalidated for this user
    if user and InvalidatedToken.objects.filter(token=token, user=user).exists():
        raise ValueError("Token has been invalidated for this user")

    try:
        payload = jwt.decode(token, settings.PUBLIC_KEY, algorithms=["RS256"])
        if payload["type"] != token_type:
            raise ValueError("Incorrect token type")
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token expired")
    except jwt.DecodeError:
        raise ValueError("Invalid token")


def generate_short_term_token(user_id, email, role_name):
    """Generates a short-lived JWT token (e.g., 30 minutes) for frontend verification."""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role_name,
        "type": "access",
        "jti": str(uuid.uuid4()),
        "exp": timezone.now() + timedelta(minutes=30),
        "iat": timezone.now(),
    }
    return jwt.encode(payload, settings.PRIVATE_KEY, algorithm="RS256")


def generate_long_term_token(user_id, email, role_name):
    """Generates a long-lived refresh JWT token (e.g., 1 day) for API access authorization."""
    payload = {
        "user_id": user_id,
        "email": email,
        "role": role_name,
        "type": "refresh",
        "jti": str(uuid.uuid4()),
        "exp": timezone.now() + timedelta(days=1),
        "iat": timezone.now(),
    }
    return jwt.encode(payload, settings.PRIVATE_KEY, algorithm="RS256")


#
