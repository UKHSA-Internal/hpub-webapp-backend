import logging
import os
import sys
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
from rest_framework import status, generics
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
    """
    API endpoint for signing up a new user based on a decoded Azure B2C token.
    """

    permission_classes = [AllowAny]

    def post(self, request):
        # Step 1: Validate token from header.
        decoded_token = self._get_decoded_token(request)
        if isinstance(decoded_token, Response):
            return decoded_token

        # Step 2: Extract and validate user info.
        user_info = self._extract_user_info(decoded_token)
        if isinstance(user_info, Response):
            return user_info

        first_name = user_info["first_name"]
        last_name = user_info["last_name"]
        email = user_info["email"]
        mobile_number = user_info["mobile_number"]
        role_name = user_info["role_name"]

        # Validate email format.
        try:
            validate_email(email)
        except ValidationError:
            logger.error("Invalid email format: %s", email)
            return Response(
                {"error": "Invalid email format"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Step 3: Check for an existing user.
        if User.objects.filter(email=email).exists():
            logger.info("User with email %s already exists.", email)
            existing_user = User.objects.get(email=email)
            return self._return_user(
                existing_user,
                email,
                role_name,
                message=USER_EXISTS_MSG,
                status_code=status.HTTP_200_OK,
            )

        # Step 4: Validate Role.
        role = None
        if role_name:
            role = Role.objects.filter(name=role_name).first()
        if role_name and not role:
            logger.error("Role not found: %s", role_name)
            return Response(
                {"error": "Role not found"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Step 5: Validate Establishment (if provided).
        establishment_result = self._get_establishment_and_org(request)
        if isinstance(establishment_result, Response):
            return establishment_result
        establishment, organization_ref = establishment_result

        # Step 6: Retrieve or create the parent 'users' page.
        parent_page = self._get_or_create_parent_page()
        if isinstance(parent_page, Response):
            return parent_page

        # Step 7: Create the user instance.
        try:
            new_user_page = self._create_user_instance(
                parent_page,
                first_name,
                last_name,
                email,
                mobile_number,
                establishment,
                organization_ref,
                role,
            )
        except (IntegrityError, Exception) as ex:
            return self._handle_create_user_error(ex, email, role_name)

        # Step 8: Generate tokens and return response.
        return self._return_user(
            new_user_page, email, role_name, status_code=status.HTTP_201_CREATED
        )

    def _handle_create_user_error(self, ex, email, role_name):
        error_str = str(ex)
        if isinstance(ex, IntegrityError):
            logger.error("Integrity error while creating user: %s", error_str)
        else:
            logger.error("Failed to create user: %s", error_str)

        if (
            "User with this Email already exists" in error_str
            or "Page with this Path already exists" in error_str
            or isinstance(ex, IntegrityError)
        ):
            existing_user = User.objects.filter(email=email).first()
            if existing_user:
                return self._return_user(
                    existing_user,
                    email,
                    role_name,
                    message=USER_EXISTS_MSG,
                    status_code=status.HTTP_200_OK,
                )

        err_msg = (
            "Integrity error while creating user page"
            if isinstance(ex, IntegrityError)
            else "Failed to create user page"
        )
        return Response(
            {"error": err_msg},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    def _get_decoded_token(self, request):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            logger.error("Authorization header missing or improperly formatted.")
            return Response(
                {"error": "Invalid or missing Authorization token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            token = auth_header.split(" ")[1]
        except IndexError:
            logger.error("Authorization token not found after splitting header.")
            return Response(
                {"error": "Invalid Authorization header format"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        try:
            decoded_token = validate_azure_b2c_token(token)
            logger.info("Successfully decoded token: %s", decoded_token)
            return decoded_token
        except Exception as e:
            logger.error("Token validation error: %s", str(e))
            return Response(
                {"error": f"Invalid token: {str(e)}"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

    def _extract_user_info(self, decoded_token):
        first_name = decoded_token.get("given_name", "").strip()
        last_name = decoded_token.get("family_name", "").strip()
        mobile_number = decoded_token.get("mobile_number", "").strip()
        # Try to get email from one of two possible keys.
        email = decoded_token.get("email_address") or decoded_token.get("email")
        if email:
            email = email.strip()
        role_name = decoded_token.get("user_approle", "").strip() or "User"
        logger.info(
            "Extracted user_info: first_name=%s, last_name=%s, email=%s, role_name=%s",
            first_name,
            last_name,
            email,
            role_name,
        )
        if not email:
            return Response(
                {"error": "Email not found in token"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return {
            "first_name": first_name,
            "last_name": last_name,
            "email": email,
            "mobile_number": mobile_number,
            "role_name": role_name,
        }

    def _get_establishment_and_org(self, request):
        establishment_id = request.data.get("establishment_id")
        if not establishment_id:
            return None, None
        establishment = Establishment.objects.filter(
            establishment_id=establishment_id
        ).first()
        if not establishment:
            logger.error("Establishment not found: %s", establishment_id)
            return Response(
                {"error": "Establishment not found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        return establishment, establishment.organization_ref

    def _get_or_create_parent_page(self):
        try:
            parent_page = Page.objects.get(slug="users")
            logger.info("Parent page 'users' found.")
            return parent_page
        except Page.DoesNotExist:
            logger.warning("Parent page 'users' not found. Attempting to create one.")
            root_page = Page.objects.first()
            if not root_page:
                logger.error("No root page available to attach 'users' page.")
                return Response(
                    {"error": "Root page not found"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
            parent_page = Page(
                title="Users",
                slug="users",
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            logger.info("Parent page 'users' created.")
            return parent_page

    def _create_user_instance(
        self,
        parent_page,
        first_name,
        last_name,
        email,
        mobile_number,
        establishment,
        organization_ref,
        role,
    ):
        unique_slug = slugify(f"user-{first_name}-{last_name}-{uuid.uuid4()}")
        user_instance = User(
            title=f"User: {first_name} {last_name}",
            slug=unique_slug,
            user_id=str(uuid.uuid4()),
            email=email,
            first_name=first_name,
            last_name=last_name,
            email_verified=True,
            is_authorized=True,
            mobile_number=mobile_number,
            establishment_ref=establishment,
            organization_ref=organization_ref,
            role_ref=role,
        )
        with transaction.atomic():
            new_user_page = parent_page.add_child(instance=user_instance)
        logger.info("User instance created successfully: %s", new_user_page)
        return new_user_page

    def _return_user(
        self, user_page, email, role_name, message=None, status_code=status.HTTP_200_OK
    ):
        """
        Helper method to generate tokens and return the user data.
        Includes a message only if provided (for existing users).
        """
        user_response_data = UserSerializer(user_page).data
        try:
            short_term_token = generate_short_term_token(
                user_page.user_id, email, role_name
            )
            long_term_token = generate_long_term_token(
                user_page.user_id, email, role_name
            )
        except Exception as token_error:
            logger.error("Token generation failed: %s", str(token_error))
            return Response(
                {"error": "Failed to generate authentication tokens"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
        response_data = {
            "user": user_response_data,
            "short_term_token": short_term_token,
        }
        if message:
            response_data["message"] = message
        response = Response(response_data, status=status_code)

        response.set_cookie(
            key="long_term_token",
            value=long_term_token,
            httponly=True,
            secure=(not settings.DEBUG),
            samesite="Lax",  # or "Strict"/"None" based on frontend-backend setup
            max_age=86400,  # 1 day
        )
        return response


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
        # 1. Blank checks
        if self._is_blank(raw):
            return None

        # 2. Try each parser in turn
        for parser in (
            self._parse_timestamp,
            self._parse_known_formats,
            self._parse_pandas,
            self._parse_dateutil,
        ):
            dt = parser(raw)
            if dt is not None:
                return dt

        # 3. If all fail
        return None

    def _is_blank(self, raw):
        return raw in (None, "", "-", "N/A") or pd.isna(raw)

    def _make_aware_if_needed(self, dt):
        if dt.year < 1900:
            return None
        return timezone.make_aware(dt) if timezone.is_naive(dt) else dt

    def _parse_timestamp(self, raw):
        if isinstance(raw, pd.Timestamp) or isinstance(raw, datetime.datetime):
            dt = raw.to_pydatetime() if isinstance(raw, pd.Timestamp) else raw
            return self._make_aware_if_needed(dt)
        return None

    def _parse_known_formats(self, raw):
        s = str(raw).strip()
        for fmt in ("%d-%b-%Y %H:%M:%S", "%m/%d/%Y %I:%M:%S %p"):
            try:
                dt = datetime.datetime.strptime(s, fmt)
                return self._make_aware_if_needed(dt)
            except ValueError:
                continue
        return None

    def _parse_pandas(self, raw):
        try:
            dt = pd.to_datetime(str(raw), errors="coerce")
            if not pd.isna(dt):
                return self._make_aware_if_needed(dt.to_pydatetime())
        except Exception:
            pass
        return None

    def _parse_dateutil(self, raw):
        try:
            dt = dateutil_parser.parse(str(raw))
            return self._make_aware_if_needed(dt)
        except Exception:
            logger.warning("Unable to parse date: '%s'", raw)
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
