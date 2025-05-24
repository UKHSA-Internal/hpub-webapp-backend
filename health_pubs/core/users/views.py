import logging
import os
import sys
from typing import Optional, Tuple
import uuid
import pandas as pd
from dateutil import parser as dateutil_parser

from django.utils import timezone
import datetime

from core.organizations.models import Organization
from core.users.permissions import IsAdminUser
import jwt
import requests
from configs.get_secret_config import Config
from core.establishments.models import Establishment
from core.roles.models import Role
from core.utils.convert_jwks_token_pem import get_pem_from_jwks
from core.utils.custom_token_authentication import CustomTokenAuthentication
from core.utils.token_generation_validation import (
    generate_long_term_token,
    generate_short_term_token,
    validate_token,
    validate_token_refresh,
)
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.validators import validate_email
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status, generics, exceptions
from rest_framework.status import HTTP_204_NO_CONTENT
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from rest_framework.authentication import SessionAuthentication
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.models import Page
from django.db import transaction, DatabaseError, IntegrityError

from .models import InvalidatedToken, User
from .serializers import UserSerializer
import health_pubs.settings as settings

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


# Setup logger
logger = logging.getLogger(__name__)

config = Config()

# Constants
USER_EXISTS_MSG = "User already exists"

TOKEN_ISSUER_DOMAIN = "ciamlogin.com"


# Helper function to validate Azure B2C token


def refresh_b2c_token(refresh_token):
    """Refreshes Azure B2C access token using the refresh token."""
    client_id = config.get_azure_b2c_client_id()
    tenant_name = config.get_azure_b2c_tenant_name()
    tenant_id = config.get_azure_b2c_tenant_id()

    token_url = (
        f"https://{tenant_name}.{TOKEN_ISSUER_DOMAIN}/{tenant_id}/oauth2/v2.0/token"
    )

    # Prepare the data for refreshing the token
    data = {
        "client_id": client_id,
        "grant_type": "refresh_token",
        "scope": "openid profile offline_access",
        "refresh_token": refresh_token,
    }

    response = requests.post(token_url, data=data)
    if response.status_code == 200:
        new_tokens = response.json()
        return new_tokens["access_token"], new_tokens["refresh_token"]
    else:
        raise ValueError("Failed to refresh token")


def validate_azure_b2c_token(token):
    client_id = config.get_azure_b2c_client_id()
    jwks_url = config.get_azure_b2c_jwks_uri()
    try:
        # Fetch JWKS
        jwks = requests.get(jwks_url).json()
        unverified_header = jwt.get_unverified_header(token)
        token_kid = unverified_header.get("kid")

        # Log all available kids in JWKS
        available_kids = [key["kid"] for key in jwks["keys"]]
        logger.info(f"Number of keys in JWKS: {len(available_kids)}")  # for debugging

        # Select the correct key based on kid
        rsa_key = {}
        for key in jwks["keys"]:
            if key["kid"] == token_kid:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
                break

        if not rsa_key:
            raise ValueError("Unable to find appropriate key for token")

        pem_key = get_pem_from_jwks(rsa_key)

        # Decode and validate the token
        decoded_token = jwt.decode(
            token,
            pem_key,
            algorithms=["RS256"],
            audience=client_id,
            issuer=f"https://{config.get_azure_b2c_tenant_id()}.{TOKEN_ISSUER_DOMAIN}/{config.get_azure_b2c_tenant_id()}/v2.0",
        )
        # logger.info("decoded_token", decoded_token) #for debugging
        return decoded_token

    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidTokenError:
        raise ValueError("Invalid token")
    except Exception as e:
        logger.error(f"Error validating token: {str(e)}")
        raise ValueError("Token validation failed")


class UserSignUpView(APIView):
    """Handles post-signup user creation and token issuance."""

    permission_classes = [AllowAny]

    def post(self, request):
        # 1. Extract and validate the raw token
        id_token = self._get_bearer_token(request)
        claims = self._validate_b2c_token(id_token)

        # 2. Pull out and verify user attributes
        user_data = self._extract_and_validate_claims(claims, request.data)

        # 3. Load related objects
        role = self._get_role(user_data.pop("role_name"))
        establishment, organization = self._get_establishment_and_org(
            user_data.pop("establishment_id")
        )

        # 4. Find or create the Wagtail user page
        user_page, created = self._find_or_create_user_page(
            user_data, role, establishment, organization
        )

        # 5. Issue JWTs
        short_token, long_token = self._generate_tokens(
            user_page, user_data["role_name"]
        )

        # 6. Build the response
        return self._build_response(user_page, created, short_token, long_token)

    # ───────────────────────────────────────────────────────────────────────────────
    # 1) AUTH HEADER & TOKEN VALIDATION
    # ───────────────────────────────────────────────────────────────────────────────

    def _get_bearer_token(self, request) -> str:
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            raise exceptions.AuthenticationFailed(
                "Missing or malformed Authorization header"
            )
        return auth.split(" ", 1)[1]

    def _validate_b2c_token(self, token: str) -> dict:
        try:
            return validate_token(token, token_type="access")
        except Exception as e:
            logger.warning("B2C token invalid: %s", e, exc_info=True)
            raise exceptions.AuthenticationFailed("Invalid token")

    # ───────────────────────────────────────────────────────────────────────────────
    # 2) CLAIM EXTRACTION & VALIDATION
    # ───────────────────────────────────────────────────────────────────────────────

    def _extract_and_validate_claims(self, claims: dict, data: dict) -> dict:
        # Normalize and validate email
        email = (
            (claims.get("email") or claims.get("email_address") or "").lower().strip()
        )
        if not email:
            raise exceptions.ValidationError("Email missing in token")
        try:
            validate_email(email)
        except ValidationError:
            raise exceptions.ValidationError("Invalid email format")

        return {
            "email": email,
            "first_name": (claims.get("given_name") or "").strip(),
            "last_name": (claims.get("family_name") or "").strip(),
            "mobile_number": (claims.get("mobile_number") or "").strip(),
            "role_name": (claims.get("user_approle") or "").strip() or None,
            "establishment_id": data.get("establishment_id"),
        }

    # ───────────────────────────────────────────────────────────────────────────────
    # 3) ROLE & ESTABLISHMENT LOADING
    # ───────────────────────────────────────────────────────────────────────────────

    def _get_role(self, role_name: Optional[str]) -> Optional[Role]:
        if not role_name:
            return None
        role = Role.objects.filter(name=role_name).first()
        if not role:
            raise exceptions.ValidationError("Role not found")
        return role

    def _get_establishment_and_org(
        self, est_id: Optional[str]
    ) -> Tuple[Optional[Establishment], Optional[Organization]]:
        if not est_id:
            return None, None
        est = Establishment.objects.filter(establishment_id=est_id).first()
        if not est:
            raise exceptions.NotFound("Establishment not found")
        return est, est.organization_ref

    # ───────────────────────────────────────────────────────────────────────────────
    # 4) USER PAGE CREATION
    # ───────────────────────────────────────────────────────────────────────────────

    def _find_or_create_user_page(self, info, role, est, org) -> Tuple[User, bool]:
        try:
            user = User.objects.get(email=info["email"])
            return user, False
        except User.DoesNotExist:
            parent = self._get_or_create_parent_page()
            unique_slug = slugify(
                f"user-{info['first_name']}-{info['last_name']}-{uuid.uuid4()}"
            )
            user = User(
                title=f"{info['first_name']} {info['last_name']}".strip()
                or info["email"],
                slug=unique_slug,
                user_id=str(uuid.uuid4()),
                **info,
                role_ref=role,
                establishment_ref=est,
                organization_ref=org,
                email_verified=True,
                is_authorized=True,
            )
            try:
                with transaction.atomic():
                    parent.add_child(instance=user)
                return user, True
            except IntegrityError as e:
                logger.error("DB error creating user: %s", e, exc_info=True)
                raise exceptions.APIException("Database error creating user")

    def _get_or_create_parent_page(self) -> Page:
        page, created = Page.objects.get_or_create(
            slug="users",
            defaults={
                "title": "Users",
                "content_type": ContentType.objects.get_for_model(Page),
                "path": Page.get_first_root_node().path,
                "depth": Page.get_first_root_node().depth + 1,
            },
        )
        return page

    # ───────────────────────────────────────────────────────────────────────────────
    # 5) TOKEN GENERATION
    # ───────────────────────────────────────────────────────────────────────────────

    def _generate_tokens(self, user: User, role_name: Optional[str]) -> Tuple[str, str]:
        try:
            short = generate_short_term_token(user.user_id, user.email, role_name)
            long = generate_long_term_token(user.user_id, user.email, role_name)
            return short, long
        except Exception as e:
            logger.error("Token generation failed: %s", e, exc_info=True)
            raise exceptions.APIException("Token generation failed")

    # ───────────────────────────────────────────────────────────────────────────────
    # 6) RESPONSE BUILDING
    # ───────────────────────────────────────────────────────────────────────────────

    def _build_response(
        self, user: User, created: bool, short: str, long: str
    ) -> Response:
        serializer = UserSerializer(user)
        payload = {"user": serializer.data, "short_term_token": short}
        if not created:
            payload["message"] = USER_EXISTS_MSG

        resp = Response(
            payload, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )
        resp.set_cookie(
            "long_term_token",
            long,
            httponly=True,
            secure=not settings.DEBUG,
            samesite="Lax",
            max_age=86400,
        )
        return resp


class UserLoginView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return Response(
                {"error": "Authorization token missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            token = auth_header.split(" ")[1]
            decoded_token = validate_azure_b2c_token(token)
            email = (
                decoded_token.get("email_address")
                if "email_address" in decoded_token
                else None
            )
        except (IndexError, ValueError) as e:
            return Response({"error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        if not email:
            return Response(
                {"error": "Email not found in token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.filter(email=email).first()
        if user is None:
            return Response(
                {"error": "User not found"}, status=status.HTTP_404_NOT_FOUND
            )
        # Debug print user information
        logger.info("User found: %s", user)

        # Update the last_login field upon successful login.
        user.update_last_login()
        user.save(update_fields=["last_login"])
        logger.info("Updated last_login for user: %s", user.user_id)

        # Retrieve role
        role_ref = user.role_ref
        if role_ref:
            logger.info("Role found: %s", role_ref)
            logger.info("Role name: %s", role_ref.name)
            role_name = role_ref.name
        else:
            logger.info("No role found for role_ref: %s", user.role_ref)
            role_name = None

        # Retrieve organization
        organization_ref = user.organization_ref
        if organization_ref:
            logger.info("Organization found: %s", organization_ref)
            logger.info("Organization name: %s", organization_ref.name)
            organization_name = organization_ref.name
        else:
            logger.info("No role found for organization_ref: %s", user.organization_ref)
            organization_name = None
        short_term_token = generate_short_term_token(
            user.user_id, user.email, role_name
        )
        long_term_token = generate_long_term_token(user.user_id, user.email, role_name)

        # Prepare response data (do not include long_term_token in body)
        response_data = {
            "short_term_token": short_term_token,
            "organization_name": organization_name,
        }
        response = Response(response_data, status=status.HTTP_200_OK)

        # Set long-term token as HTTP-only, secure cookie.
        response.set_cookie(
            key="long_term_token",
            value=long_term_token,
            httponly=True,
            secure=(not settings.DEBUG),  # Only send over HTTPS.
            samesite="Lax",  # Adjust as needed ("Strict" or "None")
            max_age=86400,  # Lifetime in seconds (here, 1 day)
        )

        return response


class UpdateUserView(APIView):
    permission_classes = [AllowAny]

    def put(self, request):
        user_id = request.data.get("user_id")
        if not user_id:
            return Response(
                {"error": "User ID is required"}, status=status.HTTP_400_BAD_REQUEST
            )
        # Step 1: Verify the authenticated user's identity and role
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return Response(
                {"error": "Authorization token missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        # Step 2: Retrieve the user by user_id
        user_instance = get_object_or_404(User, user_id=user_id)

        # Step 3: Retrieve and validate establishment_id if provided
        establishment_id = request.data.get("establishment_id")
        if establishment_id:
            establishment = Establishment.objects.filter(
                establishment_id=establishment_id
            ).first()
            if not establishment:
                return Response(
                    {"error": "Establishment not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            user_instance.establishment_ref = establishment
            user_instance.organization_ref = establishment.organization_ref

        # Step 4: Save changes to the user
        try:
            user_instance.save()
            return Response(
                {"message": "User updated successfully"}, status=status.HTTP_200_OK
            )
        except Exception as ex:
            logger.error(f"Failed to update user: {str(ex)}")
            return Response(
                {"error": "Failed to update user"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class TokenRefresh(APIView):
    """
    Refresh endpoint:
      - Manually extracts the refresh token from the Authorization header or cookies.
      - Validates the refresh token (handling expiration as needed).
      - Issues a new short-term token.
      - IMPORTANTLY: It sets (or resets) the long‑term refresh token cookie on the response.
    """

    # Remove default authentication so expired tokens can be processed.
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        logger.info("Request COOKIE header: %s", request.META.get("HTTP_COOKIE"))
        # Extract token from header if available; otherwise use cookie.
        auth_header = request.headers.get("Authorization", "")
        if auth_header and " " in auth_header:
            refresh_token = auth_header.split(" ")[1]
            logger.info("Refresh token from header: %s", refresh_token)
        else:
            refresh_token = request.COOKIES.get("long_term_token")
            logger.info("Refresh token from cookies: %s", refresh_token)

        if not refresh_token:
            return Response(
                {"error": "Refresh token missing"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            # Validate the refresh token.
            payload = validate_token_refresh(refresh_token, token_type="refresh")
        except jwt.ExpiredSignatureError:
            # For example, if using Azure B2C flow: attempt to refresh the underlying token.
            try:
                new_access_token, new_refresh_token = refresh_b2c_token(refresh_token)
                payload = validate_token(new_access_token, token_type="access")
                # Optionally update refresh_token variable with new_refresh_token:
                refresh_token = new_refresh_token
                # Proceed with the new access token payload.
            except Exception as e:
                logger.error("Token refresh error: %s", e)
                return Response(
                    {"error": "Unable to refresh token"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
        except Exception as e:
            logger.error("Token validation error: %s", e)
            return Response({"error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        user_id = payload.get("user_id")
        email = payload.get("email")
        role = payload.get("role")

        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "User does not exist"}, status=status.HTTP_404_NOT_FOUND
            )

        if not user.is_authorized:
            return Response(
                {"error": "User is not authorized"}, status=status.HTTP_403_FORBIDDEN
            )

        # Generate a new short-term (access) token.
        new_short_term_token = generate_short_term_token(user_id, email, role)

        # Prepare the response and set the long-term refresh token cookie.
        response = Response(
            {"short_term_token": new_short_term_token}, status=status.HTTP_200_OK
        )
        # This call sets the "long_term_token" cookie with your current refresh token.
        response.set_cookie(
            key="long_term_token",
            value=refresh_token,  # Use the new refresh token if applicable
            httponly=True,
            secure=(not settings.DEBUG),  # Set to True if using HTTPS
            samesite="Lax",  # Adjust samesite if necessary (or use "Lax" or "Strict")
            max_age=86400,  # 1 day (or adjust as needed)
        )

        return response


class LogoutView(APIView):
    """
    Logout endpoint:
      - Extracts and decodes the token (even if expired) to identify the user.
      - Invalidates the token to prevent reuse.
      - Optionally instructs the client to remove the refresh token cookie.
    """

    authentication_classes = []
    permission_classes = []

    def post(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header or " " not in auth_header:
            return Response(
                {"error": "Authorization token missing or improperly formatted"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        token = auth_header.split(" ")[1]
        try:
            # Decode token ignoring expiration while still verifying its signature.
            payload = jwt.decode(
                token,
                settings.PUBLIC_KEY,  # Verify signature using the public key
                algorithms=["RS256"],
                options={"verify_exp": False},  # Only ignore expiration
            )
            user_id = payload.get("user_id")
        except Exception as e:
            logger.error("Error decoding token: %s", str(e))
            return Response(
                {"error": f"Error processing logout: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(user_id=user_id)
        except User.DoesNotExist:
            return Response(
                {"error": "User does not exist"}, status=status.HTTP_404_NOT_FOUND
            )

        # Check if this token has already been invalidated.
        if InvalidatedToken.objects.filter(token=token).exists():
            logger.info("Token already invalidated. Skipping duplicate invalidation.")
        else:
            try:
                root_page = Page.get_first_root_node()
                invalidated_token_page = InvalidatedToken(
                    title=f"Invalidated Token for {user.email}",
                    slug=slugify(f"user-{user.email}-{timezone.now().timestamp()}"),
                    users=user,
                    token=token,
                )
                try:
                    root_page.add_child(instance=invalidated_token_page)
                except IntegrityError as e:
                    if "wagtailcore_page_path_key" in str(e):
                        logger.info(
                            "Duplicate page path encountered during invalidation; ignoring error."
                        )
                    else:
                        raise
            except Exception as e:
                logger.error("Error saving invalidated token: %s", str(e))
                return Response(
                    {"error": "Error processing logout"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Optionally: instruct the client to remove the long-term cookie.
        response = Response(
            {"message": "Successfully logged out"}, status=status.HTTP_200_OK
        )
        response.delete_cookie("long_term_token")
        return response


class PreRegistrationView(APIView):
    """
    Called by Azure B2C (Pre-user-registration API connector).
    Creates the Wagtail User page *before* B2C writes the account.
    Returns HTTP 200 if OK; any 4xx/5xx halts the B2C signup and surfaces the error.
    """

    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        # 0) Verify shared secret so only Azure can hit this
        secret = request.headers.get("X-PreReg-Secret")
        if secret != settings.PRE_REG_SECRET:
            logger.warning("Unauthorized pre-registration attempt")
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        data = request.data
        first_name = (data.get("givenName") or "").strip()
        last_name = (data.get("surname") or "").strip()
        email = (data.get("email") or "").strip().lower()
        mobile_number = (data.get("mobileNumber") or "").strip()
        role_name = (data.get("userAppRole") or "").strip() or None

        # 1) Validate email presence & format
        if not email:
            return Response(
                {"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Invalid email format"}, status=status.HTTP_400_BAD_REQUEST
            )

        # 2) Check for existing user page
        if User.objects.filter(email=email).exists():
            return Response(
                {"error": "User already exists"}, status=status.HTTP_409_CONFLICT
            )

        # 3) Find-or-create parent “Users” page
        try:
            parent = Page.objects.get(slug="users")
        except Page.DoesNotExist:
            root = Page.get_first_root_node()
            users_ct = ContentType.objects.get_for_model(Page)
            parent = Page(title="Users", slug="users", content_type=users_ct)
            root.add_child(instance=parent)

        # 4) Create the User page
        try:
            unique_slug = slugify(f"user-{first_name}-{last_name}-{uuid.uuid4()}")
            user_page = User(
                title=f"{(first_name + ' ' + last_name).strip() or email}",
                slug=unique_slug,
                user_id=str(uuid.uuid4()),
                email=email,
                first_name=first_name,
                last_name=last_name,
                email_verified=True,
                is_authorized=True,
                mobile_number=mobile_number,
                role_ref=Role.objects.filter(name=role_name).first(),
            )
            with transaction.atomic():
                parent.add_child(instance=user_page)

        except IntegrityError:
            logger.exception("Database integrity error during pre-registration")
            return Response(
                {"error": "Database error creating user"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        except Exception as e:
            logger.exception("Unexpected error in pre-registration")
            return Response(
                {"error": f"Unexpected error: {e}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(status=status.HTTP_200_OK)


class UserDetailView(GenericAPIView):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        user_id = self.kwargs.get("user_id")
        return get_object_or_404(User, pk=user_id)

    def get(self, request, user_id):
        user = self.get_object()
        self.check_object_permissions(request, user)
        serializer = self.get_serializer(user)
        return Response(serializer.data)

    def put(self, request, user_id):
        user = self.get_object()
        self.check_object_permissions(request, user)
        serializer = self.get_serializer(user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CustomPagination(PageNumberPagination):
    page_size = 10  # Set pagination to 10 items per page

    def get_paginated_response(self, data, status_code=200):
        response = Response(
            {
                "links": {
                    "next": self.get_next_link(),
                    "previous": self.get_previous_link(),
                },
                "count": self.page.paginator.count,
                "results": data,
            },
            status=status_code,
        )
        return response


class UserListView(generics.ListAPIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]
    queryset = User.objects.all()
    serializer_class = UserSerializer
    pagination_class = CustomPagination

    def get(self, request, *args, **kwargs):
        """
        Get a list of users with pagination.
        """
        try:
            return super().get(request, *args, **kwargs)
        except ObjectDoesNotExist:
            logger.error("Requested user list does not exist.")
            return JsonResponse({"error": "Users not found."}, status=404)
        except Exception as e:
            logger.error(f"Unexpected error in UserListView: {e}")
            return JsonResponse({"error": "An unexpected error occurred."}, status=500)


class UserDeleteAll(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated, IsAdminUser]

    def delete(self, request, *args, **kwargs):
        logger.info("Attempting to delete all users.")

        try:
            # Delete all users from the database
            deleted_count = User.objects.all().delete()
            logger.info(f"Deleted {deleted_count} users successfully.")

            return JsonResponse(
                {"message": f"Deleted {deleted_count} users successfully."},
                status=HTTP_204_NO_CONTENT,  # No content as the users are deleted
            )

        except DatabaseError:
            logger.exception("Database error occurred while deleting all users.")
            return JsonResponse(
                {"error": "A database error occurred while deleting users."},
                status=500,
            )
        except Exception:
            logger.exception("An unexpected error occurred while deleting all users.")
            return JsonResponse(
                {"error": "An internal server error occurred."},
                status=500,
            )


class MigrateUsersAPIView(APIView):
    authentication_classes = [SessionAuthentication]
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        logger.info("Migration process started.")

        users_file = request.FILES.get("users_excel")
        if not users_file:
            logger.error("No users file provided in the request.")
            return JsonResponse(
                {"error": "Users file is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        users_df = self._read_excel_file(users_file)
        missing = self._validate_required_fields(users_df)
        if missing:
            return JsonResponse(
                {"error": f"Missing required fields: {', '.join(missing)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parent_page = self.get_or_create_parent_page(slug="users", title="Users")
        self._process_users(users_df, parent_page)

        logger.info("User migration completed successfully.")
        return JsonResponse(
            {"message": "User migration completed successfully."},
            status=status.HTTP_200_OK,
        )

    def get_or_create_parent_page(self, slug, title):
        try:
            parent = Page.objects.get(slug=slug)
            logger.info(f"Parent page '{title}' found.")
        except Page.DoesNotExist:
            logger.warning(f"Parent page '{title}' not found, creating.")
            root = Page.objects.first()
            parent = Page(
                title=title,
                slug=slug,
                content_type=ContentType.objects.get_for_model(Page),
            )
            root.add_child(instance=parent)
            logger.info(f"Parent page '{title}' created.")
        return parent

    def _read_excel_file(self, users_file):
        try:
            df = pd.read_excel(users_file)
            logger.info("Excel read, %d records", len(df))
            return df
        except Exception as e:
            logger.error("Error reading Excel: %s", e)
            raise ValueError("Failed to read Excel file.")

    def _validate_required_fields(self, df):
        required = ["user_id", "email", "first_name"]
        return [f for f in required if f not in df.columns]

    def _process_users(self, df, parent_page):
        existing_emails = set(
            User.objects.filter(email__in=df["email"]).values_list("email", flat=True)
        )

        for _, row in df.iterrows():
            email = row["email"]
            if email in existing_emails:
                logger.info("Skipping existing %s", email)
                continue

            data = self.extract_user_data(row)

            # reload parent so tree-state is fresh
            fresh_parent = Page.objects.get(pk=parent_page.pk)
            self._create_and_insert_user(data, fresh_parent)

    def extract_user_data(self, row):
        raw_id = row.get("user_id")
        user_id = str(raw_id) if pd.notnull(raw_id) else str(uuid.uuid4())
        attempts = 0
        while User.objects.filter(user_id=user_id).exists() and attempts < 5:
            user_id = str(uuid.uuid4())
            attempts += 1
        if User.objects.filter(user_id=user_id).exists():
            raise ValueError("Could not generate unique user_id")

        return {
            "user_id": user_id,
            "email": row["email"],
            "mobile_number": row.get("mobile_number"),
            "first_name": row["first_name"],
            "last_name": row.get("last_name"),
            "email_verified": row.get("email_verified"),
            "is_authorized": row.get("is_authorized"),
            "last_login": self.parse_datetime_field(row.get("last_login")),
            "created_at": self.parse_datetime_field(row.get("created_at")),
            "establishment_ref": (
                self._get_establishment_ref(int(row["establishment_id"]))
                if pd.notnull(row.get("establishment_id"))
                else None
            ),
            "organization_ref": (
                self._get_organization_ref(int(row["organization_id"]))
                if pd.notnull(row.get("organization_id"))
                else None
            ),
            "role_ref": (
                self._get_role_ref(int(row["role_id"]))
                if pd.notnull(row.get("role_id"))
                else None
            ),
        }

    def parse_datetime_field(self, raw):
        if raw in (None, "", "-", "N/A") or pd.isna(raw):
            return None

        if isinstance(raw, (pd.Timestamp, datetime.datetime)):
            dt = raw.to_pydatetime() if isinstance(raw, pd.Timestamp) else raw
            if dt.year < 1900:
                return None
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt

        s = str(raw).strip()
        for fmt in ("%d-%b-%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p"):
            try:
                dt = datetime.datetime.strptime(s, fmt)
                if dt.year < 1900:
                    return None
                return timezone.make_aware(dt)
            except ValueError:
                continue

        try:
            dt = pd.to_datetime(s, errors="coerce")
            if not pd.isna(dt) and dt.year >= 1900:
                dt = dt.to_pydatetime()
                return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
        except Exception:
            pass

        try:
            dt = dateutil_parser.parse(s)
            if dt.year < 1900:
                return None
            return timezone.make_aware(dt) if timezone.is_naive(dt) else dt
        except Exception:
            logger.warning("Unable to parse date: '%s'", s)
            return None

    def _create_and_insert_user(self, data, parent):
        try:
            if User.objects.filter(email=data["email"]).exists():
                logger.info("User exists, skipping: %s", data["email"])
                return

            slug = slugify(f"user-{data['email']}-{uuid.uuid4()}")
            inst = User(
                title=f"User {data['first_name']}",
                slug=slug,
                user_id=data["user_id"],
                email=data["email"],
                mobile_number=data["mobile_number"],
                first_name=data["first_name"],
                last_name=data["last_name"],
                email_verified=data["email_verified"],
                is_authorized=data["is_authorized"],
                establishment_ref=data["establishment_ref"],
                organization_ref=data["organization_ref"],
                role_ref=data["role_ref"],
                last_login=data["last_login"],
            )

            if data.get("created_at"):
                inst.created_at = data["created_at"]

            # this add_child always sees the up-to-date tree in the DB
            parent.add_child(instance=inst)
            logger.info("Created user: %s", data["email"])

        except ValidationError as ve:
            logger.error("ValidationError %s: %s", data["email"], ve)
            raise
        except Exception as e:
            logger.error("Error creating %s: %s", data["email"], e)
            raise

    def _get_establishment_ref(self, eid):
        try:
            return Establishment.objects.get(establishment_id=eid)
        except Establishment.DoesNotExist:
            logger.warning("Establishment %s not found", eid)
            return None

    def _get_organization_ref(self, oid):
        try:
            return Organization.objects.get(organization_id=oid)
        except Organization.DoesNotExist:
            logger.warning("Organization %s not found", oid)
            return None

    def _get_role_ref(self, rid):
        try:
            return Role.objects.get(role_id=rid)
        except Role.DoesNotExist:
            logger.warning("Role %s not found", rid)
            return None


#
