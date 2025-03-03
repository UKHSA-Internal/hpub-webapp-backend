import logging
import os
import sys
import uuid
import pandas as pd

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
            "long_term_token": long_term_token,
        }
        if message:
            response_data["message"] = message
        return Response(response_data, status=status_code)


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

        return Response(
            {
                "short_term_token": short_term_token,
                "long_term_token": long_term_token,
                "organization_name": organization_name,
            },
            status=status.HTTP_200_OK,
        )


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


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # Get the token from the request headers
        auth_header = request.headers.get("Authorization", "")
        if not auth_header:
            return Response(
                {"error": "Authorization token missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            # Extract token
            token = auth_header.split(" ")[1]

            # Decode token without verification to extract user_id
            unverified_payload = jwt.decode(token, options={"verify_signature": False})
            user_id = unverified_payload.get("user_id")

            # Get the user from the User model
            user = User.objects.get(user_id=user_id)

            # Create and save an InvalidatedToken page as a child of the root page
            root_page = (
                Page.get_first_root_node()
            )  # You can change this to a different parent page as needed
            invalidated_token_page = InvalidatedToken(
                title=f"Invalidated Token for {user.email}",
                slug=slugify(f"user-{user.email}-{timezone.now().timestamp()}"),
                users=user,
                token=token,
            )
            root_page.add_child(instance=invalidated_token_page)
            invalidated_token_page.save()

        except (jwt.DecodeError, IndexError, User.DoesNotExist) as e:
            return Response(
                {"error": f"Error processing logout: {str(e)}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {"message": "Successfully logged out"}, status=status.HTTP_200_OK
        )


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


class TokenRefresh(APIView):
    authentication_classes = [CustomTokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # logger.info(f"Authorization header: {request.headers.get('Authorization')}") # for debugging

        # Extract the refresh token from the Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or " " not in auth_header:
            return Response(
                {"error": "Refresh token missing"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        refresh_token = auth_header.split(" ")[1]

        try:
            # Attempt to validate the refresh token
            payload = validate_token_refresh(refresh_token, token_type="refresh")
            user_id = payload.get("user_id")
            email = payload.get("email")
            role_name = payload.get("role")

            user = User.objects.get(user_id=user_id)
            if not user.is_authorized:
                return Response(
                    {"error": "User is not authorized"},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Generate a new short-term token
            new_short_term_token = generate_short_term_token(user_id, email, role_name)
            return Response(
                {"short_term_token": new_short_term_token}, status=status.HTTP_200_OK
            )

        except jwt.ExpiredSignatureError:
            # Refresh the Azure B2C token
            try:
                new_access_token, new_refresh_token = refresh_b2c_token(refresh_token)
                payload = validate_token(new_access_token, token_type="access")

                # Extract user info from the new token
                user_id = payload.get("user_id")
                email = payload.get("email")
                role_name = payload.get("role")

                # Generate a new short-term token using updated access token data
                new_short_term_token = generate_short_term_token(
                    user_id, email, role_name
                )

                return Response(
                    {
                        "short_term_token": new_short_term_token,
                        "new_access_token": new_access_token,
                        "new_refresh_token": new_refresh_token,
                    },
                    status=status.HTTP_200_OK,
                )
            except ValueError as e:
                logger.error(f"Token refresh error: {e}")
                return Response(
                    {"error": "Unable to refresh token"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

        except ValueError as e:
            logger.error(f"Token validation error: {e}")
            return Response({"error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)


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

        missing_fields = self._validate_required_fields(users_df)
        if missing_fields:
            return JsonResponse(
                {
                    "error": f"Missing required fields in users file: {', '.join(missing_fields)}"
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get or create the parent page for users
        user_parent_page = self.get_or_create_parent_page(slug="users", title="Users")

        # Process and create users in batches, under the parent page
        self._process_users(users_df, user_parent_page)

        logger.info("User migration completed successfully.")
        return JsonResponse(
            {"message": "User migration completed successfully."},
            status=status.HTTP_200_OK,
        )

    def get_or_create_parent_page(self, slug, title):
        """Retrieve or create a parent page for users."""
        try:
            parent_page = Page.objects.get(slug=slug)
            logger.info(f"Parent page '{title}' found.")
        except Page.DoesNotExist:
            logger.warning(f"Parent page '{title}' not found, creating new one.")
            try:
                root_page = Page.objects.first()
                parent_page = Page(
                    title=title,
                    slug=slug,
                    content_type=ContentType.objects.get_for_model(Page),
                )
                root_page.add_child(instance=parent_page)
                logger.info(f"Parent page '{title}' created.")
            except Exception as ex:
                logger.error(f"Failed to create parent page: {str(ex)}")
                raise
        return parent_page

    def _read_excel_file(self, users_file):
        try:
            users_df = pd.read_excel(users_file)
            logger.info(
                "Excel file read successfully. Number of records: %d", len(users_df)
            )
            return users_df
        except Exception as e:
            logger.error("Error reading Excel file: %s", str(e))
            raise ValueError("Failed to read the provided Excel file.")

    def _validate_required_fields(self, users_df):
        required_user_fields = ["user_id", "email", "first_name"]
        return [
            field for field in required_user_fields if field not in users_df.columns
        ]

    def _process_users(self, users_df, user_parent_page):
        # Get all existing user emails in one query to minimize database calls
        existing_emails = set(
            User.objects.filter(email__in=users_df["email"]).values_list(
                "email", flat=True
            )
        )
        batch_size = 25
        users_to_create = []

        for index, row in users_df.iterrows():
            # Skip users that already exist in the database
            if row["email"] in existing_emails:
                logger.info(f"User with email {row['email']} already exists. Skipping.")
                continue

            user_data = self.extract_user_data(row)
            user_instance = self._create_user_instance(user_data, user_parent_page)

            if user_instance:
                users_to_create.append(user_instance)
                logger.debug("Processed user record %d: %s", index, user_data["email"])

                # Save in batches
                if len(users_to_create) >= batch_size:
                    self._save_users_batch(users_to_create)
                    users_to_create = []

        # Save any remaining users in the last batch
        if users_to_create:
            self._save_users_batch(users_to_create)

    def _save_users_batch(self, users_batch):
        try:
            with transaction.atomic():
                for user in users_batch:
                    user.save()
            logger.info("Successfully saved a batch of %d users.", len(users_batch))
        except Exception as e:
            logger.error("Error creating users in the database: %s", str(e))

    def extract_user_data(self, row):
        user_id = row["user_id"] if pd.notnull(row["user_id"]) else str(uuid.uuid4())

        # Check if user_id already exists
        if User.objects.filter(user_id=user_id).exists():
            logger.warning(
                f"user_id '{user_id}' already exists. Generating a new UUID."
            )
            user_id = str(uuid.uuid4())

            # Optionally, add a loop to ensure uniqueness (with a max number of attempts)
            attempts = 1
            max_attempts = 5
            while (
                User.objects.filter(user_id=user_id).exists()
                and attempts <= max_attempts
            ):
                logger.warning(
                    f"Attempt {attempts}: user_id '{user_id}' already exists. Generating a new UUID."
                )
                user_id = str(uuid.uuid4())
                attempts += 1

            if User.objects.filter(user_id=user_id).exists():
                logger.error(
                    f"Failed to generate a unique user_id after {max_attempts} attempts."
                )
                raise ValueError("Unable to generate a unique user_id for the user.")
        user_data = {
            "user_id": user_id,
            "email": row["email"],
            "mobile_number": row.get("mobile_number"),
            "first_name": row["first_name"],
            "last_name": row["last_name"],
            "email_verified": row.get("email_verified"),
            "is_authorized": row.get("is_authorized"),
            "last_login": self.parse_last_login(row.get("last_login")),
            "establishment_ref": (
                self._get_establishment_ref(int(row.get("establishment_id")))
                if pd.notnull(row.get("establishment_id"))
                else None
            ),
            "organization_ref": (
                self._get_organization_ref(int(row.get("organization_id")))
                if pd.notnull(row.get("organization_id"))
                else None
            ),
            "role_ref": (
                self._get_role_ref(int(row.get("role_id")))
                if pd.notnull(row.get("role_id"))
                else None
            ),
        }
        logger.debug("Extracted user data: %s", user_data)
        return user_data

    def parse_last_login(self, last_login_str):
        if last_login_str in (None, "", "-", "N/A"):
            return None

        try:
            last_login = pd.to_datetime(last_login_str, errors="raise")

            last_login = timezone.make_aware(last_login)
            return last_login
        except ValueError:
            logger.warning(
                "Invalid date format for last_login: %s. Setting to None.",
                last_login_str,
            )
            return None

    def _create_user_instance(self, user_data, user_parent_page):
        """Create and return a User instance as a child page."""

        # Debugging output
        logging.info(f"User parent page: {user_parent_page}, User data: {user_data}")

        try:
            if pd.isna(user_data.get("last_login")):
                user_data["last_login"] = None
            user_instance = User.objects.get(email=user_data["email"])
            logging.info(f"USER_EXISTS_MSG: {user_instance}")
        except User.DoesNotExist:
            # Prepare to create a new user instance
            slug = slugify(f"user-{user_data['email']}-{str(uuid.uuid4())}")
            if User.objects.filter(slug=slug).exists():
                slug = f"{slug}-{str(uuid.uuid4())}"

            user_instance = User(
                title=f"User {user_data['first_name']}",
                slug=slug,
                user_id=user_data["user_id"],
                email=user_data["email"],
                mobile_number=user_data["mobile_number"],
                first_name=user_data["first_name"],
                last_name=user_data["last_name"],
                email_verified=user_data["email_verified"],
                is_authorized=user_data["is_authorized"],
                establishment_ref=user_data["establishment_ref"],
                organization_ref=user_data["organization_ref"],
                role_ref=user_data["role_ref"],
                last_login=user_data["last_login"],
            )

            try:
                # Set path and depth for the new user if applicable
                if user_parent_page.get_last_child() is None:
                    # Create the path and depth for the first child
                    user_instance.path = f"{user_parent_page.path}0001"
                    user_instance.depth = user_parent_page.depth + 1
                else:
                    # Use add_child() for subsequent users
                    user_parent_page.add_child(instance=user_instance)

                user_instance.save()
                logger.info(f"User '{user_data['email']}' created successfully.")
                return user_instance

            except ValidationError as e:
                logger.error(
                    f"Validation error for user '{user_data['email']}': {str(e)}"
                )
                raise

            except Exception as e:
                logger.error(f"Failed to create user '{user_data['email']}': {str(e)}")
                raise

        return user_instance

    def _get_establishment_ref(self, establishment_id):
        try:
            return Establishment.objects.get(establishment_id=establishment_id)
        except Establishment.DoesNotExist:
            logger.warning("Establishment not found for id: %s", establishment_id)
            return None

    def _get_organization_ref(self, organization_id):
        try:
            return Organization.objects.get(organization_id=organization_id)
        except Organization.DoesNotExist:
            logger.warning("Organization not found for id: %s", organization_id)
            return None

    def _get_role_ref(self, role_id):
        try:
            return Role.objects.get(role_id=role_id)
        except Role.DoesNotExist:
            logger.warning("Role not found for id: %s", role_id)
            return None


#
