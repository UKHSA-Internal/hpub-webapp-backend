import logging
import os
import sys
import uuid

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
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from rest_framework import status, viewsets
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.models import Page

from .models import InvalidatedToken, User
from .serializers import UserSerializer

sys.path.append(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


# Setup logger
logger = logging.getLogger(__name__)

config = Config()

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

        # Log the token's kid

        # Log all available kids in JWKS
        available_kids = [key["kid"] for key in jwks["keys"]]

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
    permission_classes = [AllowAny]

    def post(self, request):
        # Step 1: Retrieve and validate the Azure B2C token
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return Response(
                {"error": "Authorization token missing"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        try:
            token = auth_header.split(" ")[1]
            decoded_token = validate_azure_b2c_token(token)
            # logger.info("Decoded_Token", decoded_token) # For debugging purposes
        except (IndexError, ValueError) as e:
            return Response({"error": str(e)}, status=status.HTTP_401_UNAUTHORIZED)

        # Step 2: Extract user information from the decoded token
        user_info = {
            "first_name": decoded_token.get("given_name", ""),
            "last_name": decoded_token.get("family_name", ""),
            "mobile_number": decoded_token.get("extension_MobileNumber", ""),
            "email": (
                decoded_token.get("email_address")
                if "email_address" in decoded_token
                else None
            ),
            "role_name": decoded_token.get("extension_UserAppRole"),
        }
        logger.info(user_info)

        role_name = user_info["role_name"]

        # If the field exists but is empty, default to 'User'
        if role_name is None or role_name.strip() == "":
            role_name = "User"

        role_name = role_name

        email = user_info["email"]
        if not email:
            return Response(
                {"error": "Email not found in token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            validate_email(email)
        except ValidationError:
            return Response(
                {"error": "Invalid email format"}, status=status.HTTP_400_BAD_REQUEST
            )

        if User.objects.filter(email=email).exists():
            return Response(
                {"error": "Email already in use"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Step 3: Retrieve role based on role_name from token
        logger.info("roleName: %s", role_name)
        role = Role.objects.filter(name=role_name).first()
        if role_name and not role:
            return Response(
                {"error": "Role not found"}, status=status.HTTP_400_BAD_REQUEST
            )

        # Step 4: Retrieve establishment if provided
        establishment_id = request.data.get("establishment_id")
        establishment = None
        organization_ref = None
        if establishment_id:
            establishment = Establishment.objects.filter(
                establishment_id=establishment_id
            ).first()
            if not establishment:
                return Response(
                    {"error": "Establishment not found"},
                    status=status.HTTP_404_NOT_FOUND,
                )
            organization_ref = establishment.organization_ref

        # Step 5: Retrieve or create the parent page for the user
        try:
            parent_page = Page.objects.get(slug="users")
            logger.info("Parent page 'users' found.")
        except Page.DoesNotExist:
            logger.warning("Parent page 'users' not found, creating a new one.")
            root_page = Page.objects.first()
            parent_page = Page(
                title="Users",
                slug="users",
                content_type=ContentType.objects.get_for_model(Page),
            )
            root_page.add_child(instance=parent_page)
            logger.info("Parent page 'users' created.")

        # Step 6: Create user instance
        user_instance = User(
            title=f"User: {user_info['first_name']} {user_info['last_name']}",
            slug=slugify(
                f"user-{user_info['first_name']}-{user_info['last_name']}-{timezone.now().timestamp()}"
            ),
            user_id=str(uuid.uuid4()),
            email=email,
            first_name=user_info["first_name"],
            last_name=user_info["last_name"],
            email_verified=True,
            is_authorized=True,
            mobile_number=user_info["mobile_number"],
            establishment_ref=establishment,
            organization_ref=organization_ref,
            role_ref=role,
        )

        # Step 7: Save user and return response
        try:

            parent_page.add_child(instance=user_instance)
            user_instance.save()

            user_response_data = UserSerializer(user_instance).data

            # Generate tokens without saving them in the database
            short_term_token = generate_short_term_token(
                user_instance.user_id, email, role_name
            )
            long_term_token = generate_long_term_token(
                user_instance.user_id, email, role_name
            )

            response_data = {
                "user": user_response_data,
                "short_term_token": short_term_token,
                "long_term_token": long_term_token,
            }
            return Response(response_data, status=status.HTTP_201_CREATED)
        except Exception as ex:
            logger.error(f"Failed to create user: {str(ex)}")
            return Response(
                {"error": "Failed to create user page"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


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
    permission_classes = [IsAuthenticated]

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


#
