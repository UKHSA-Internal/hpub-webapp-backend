# Health Publication Backend API Documentation

## Overview

This project is a Wagtail-Django-based backend application for managing various health publication components such as programs, products(publications), ordering publications, and more. The project uses Wagtail to provide APIs for interacting with these components.

## Prerequisites

   Before running the project, ensure that you have the following installed:

   1. Python (3.10+)
   2. PostgreSQL, Django
   3. Environment variables (.env.dev file)
   4. pip (Python package manager)
   5. Docker (optional, for running the project in a container)
   6. Ensure your Ip is whitelisted in Aurora DB please speak with Jagan (DevOps Engineer)
   7. Install PgAdmin to visualize the db using this Link `https://ftp.postgresql.org/pub/pgadmin/pgadmin4/v8.13/windows/pgadmin4-8.13-x64.exe`
   8. Install and set up Postman to test out the endpoints.

## Getting Started

1. Clone Repository
    - `git clone <repository-url>`
    - `cd hpub-backend/backend_alpha`

2. Set Up Environment Variables

   - Create an .env.dev file in the directory `/hpub-backend/backend_alpha/configs/`

   - Ensure you have .env.dev file in the `/backend-alpha/configs/` directory.

3. Install Dependencies

   - `pip install -r requirements.txt`

4. Apply Database Migrations(Optional, this is for only if you made changes to the model structure)
   Run the following commands to apply migrations
   - `python manage.py makemigrations`

   - `python manage.py migrate`

5. Start the Development Server
   Start the Django development server with the specified port (optional), If you do not specify a port, the server will run on the default port 8000.
   - `python manage.py runserver <port>`

## Run Locally Without Access to AWS Secrets Manager

1. Create a PostgreSQL database.
2. Load the dumped data with:
```shell
pg_restore -h localhost -U <username> -d <database_name> /path/to/dump_file.dump
```
3. Create a file `local_secrets.json` inside `backend_alpha/configs` directory with the following format:

    ```json
    {
        "dev/hpub/database": "{\"HPUB_POSTGRES_CONNECTION_STRING\":\"postgresql://username:password@localhost:5432/dbname\"}",
        "hpub/postgres/connection/regex": "{\"POSTGRES_CONNECTION_REGEX\": \"postgresql://(?P<user>[^:]+):(?P<password>.+)@(?P<host>[^:]+):(?P<port>\\\\d+)/(?P<dbname>.+)$\"}",
        "REDACTED": "{\"GOV_UK_NOTIFY_API_KEY\":\"sample-gov-uk-notify-api-key\"}",
        "aps/api/key": "{\"APS_API_KEY\":\"sample-aps-api-key\"}",
        "address/verify/api/key": "{\"OS_ADDRESS_VERIFICATION_API_KEY\":\"sample-address-verification-api-key\"}",
        "address/verify/client/id": "{\"OS_ADDRESS_VERIFICATION_CLIENT_ID\":\"sample-client-id\"}",
        "address/verify/client/scope": "{\"OS_ADDRESS_VERIFICATION_CLIENT_SCOPE\":\"sample-client-scope\"}",
        "hpub-webapp/hpub-backend/": "{\"RELATIVE_PATH\":\"relative-path-placeholder\"}",
        "hpub/email/template/id/gov/notify": "{\"GOV_UK_NOTIFY_EMAIL_TEMPLATE_ID\":\"sample-email-template-id\"}",
        "hpub/sms/template/id/gov": "{\"GOV_UK_NOTIFY_SMS_TEMPLATE_ID\":\"sample-sms-template-id  \"}",
        "hpub/notify/api/url": "{\"GOV_UK_NOTIFY_API_URL\":\"shttps://dev-notify-api.example.com\"}",
        "hpub/aps/test/base/url": "{\"APS_TEST_BASE_URL\":\"shttps://dev-aps-test-base-url.example.com\"}",
        "hpub/os/address/validation/base/url": "{\"OS_ADDRESS_VERIFICATION_BASE_URL\":\"https://dev-address-validation-base-url.example.com\"}",
        "hpub/os/address/verification/token/url": "{\"OS_ADDRESS_VERIFICATION_TOKEN_URL\":\"https://dev-token-url.example.com\"}",
        "hpub/contact/us/aps/email/address": "{\"CONTACT_US_APS_EMAIL_ADDRESS\":\"contact@dev-aps.example.com\"}",
        "hpub/contact/us/template/id": "{\"CONTACT_US_TEMPLATE_ID\":\"sample-contact-us-template-id\"}",
        "hpub/azure/b2c/client/id": "{\"AZURE_B2C_CLIENT_ID\":\"sample-azure-b2c-client-id\"}",
        "hpub/azure/b2c/client/secret/id": "{\"AZURE_B2C_CLIENT_SECRET_ID\":\"sample-azure-b2c-client-secret\"}",
        "hpub/azure/b2c/tenant/id": "{\"AZURE_B2C_TENANT_ID\":\"sample-tenant-id\"}",
        "hpub/azure/b2c/tenant/name": "{\"AZURE_B2C_TENANT_NAME\":\"sample-tenant-name\"}" ,
        "hpub/azure/b2c/policy/name": "{\"AZURE_B2C_POLICY_NAME\":\"sample-policy-name\"}",
        "hpub/azure/b2c/jwks/uri": "{\"AZURE_B2C_JWKS_URI\":\"https://dev-jwks-uri.example.com"\"}",
        "hpub/django/secret/key": "{\"DJANGO_SECRET_KEY\":\"sample-django-secret-key\"}",
        "hpub/azure/b2c/issuer": "{\"AZURE_B2C_ISSUER\":\"https://dev-issuer.example.com"\"}",
        "hpub/rsa/keys": "{\"RSA_PUBLIC_KEY\": \"-----BEGIN PUBLIC KEY-----\\n123\\n-----END PUBLIC KEY-----\", \"RSA_PRIVATE_KEY\": \"-----BEGIN RSA PRIVATE KEY-----\\n123\\n-----END RSA PRIVATE KEY-----\"}"
    }
    ```
   
3. Activate env with
```shell
source /path/to/.env.dev
```
4. Run as normal with
```shell
python manage.py runserver <port>
```

## Running the Application with Docker

   If you prefer running the application in Docker, follow these steps:

   1. Ensure you have Docker installed on your machine.
   2. Build the Docker image for the project:
      - `docker build -t hpub-backend .`
   3. Run the Docker container:
      - `docker run -d -p 8000:8000 hpub-backend`
   4. The application will now be accessible at:
      - `<http://127.0.0.1:8000>`

## Accessing the Backend API through ECR

   Once the Docker image of the Health Publication Backend API has been built and pushed to Amazon ECR, you can run the application directly from the ECR image. This allows for easier deployment and scaling in production environments. Follow these steps to access the backend API through the image on ECR:

### Step 1: Authenticate Docker to Your ECR Registry

   Before pulling the image from ECR, you need to authenticate Docker to your ECR registry. You can do this using the AWS CLI:

   ```bash
   aws ecr get-login-password --region <your-region> | docker login --username AWS --password-stdin <your-account-id>.dkr.ecr.<your-region>.amazonaws.com
   ```

   Replace `<your-region>` with your AWS region (e.g., eu-west-2) and `<your-account-id>` with your AWS account ID.

### Step 2: Pull the Docker Image

   Once authenticated, you can pull the Docker image from ECR. Use the following command, replacing version4 with the appropriate tag of your image:

   ```bash
   docker pull <your-account-id>.dkr.ecr.<your-region>.amazonaws.com/hpub-image:version4

   ```

### Step 3: Run the Docker Container

   After pulling the image, you can run it as a Docker container. Ensure that you have your environment variables set up properly, either through a .env file or by passing them directly in the command line. Use the .env.sample in the root directory as a guide. Here’s an example of how to run the container:

   ```bash
   docker run -d -p 8080:8000 \
   --env-file /path/to/your/.env.dev \
   <your-account-id>.dkr.ecr.<your-region>.amazonaws.com/hpub-image:version4

   ```

- -d: Runs the container in detached mode.
- -p 8080:8000: Maps port 8000 of the container to port 8080 on your host machine.
- --env-file: Specifies the path to the .env file containing your environment variables.

### Step 4: Access the API

   Once the container is running, you can access the backend API at:

   ```bash
   [text](http://localhost:8080) or
   [text](http://127.0.0.1:8080)
   ```

   You can use tools like Postman, curl, or your web browser to send requests to the API.


## Deploying the Backend API into ECR

To be able to deploy to Docker, you need to follow the below steps

- git checkout user-management-backend-api
- git pull
- create a new branch  from user-management-backend-api `git checkout -b <branch_name>`
- cd into `hpub-backend/`
- Ensure you have `DockerFile` in the root directory
- Ensure you have `requirements.txt` in `backend-alpha/` folder
- Run docker-compose -f docker-compose.yaml build, after successful build
- Run the below steps to push to ECR:

   - aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin 897722687594.dkr.ecr.eu-west-2.amazonaws.com
   - docker tag hpub-backend_web 897722687594.dkr.ecr.eu-west-2.amazonaws.com/hpub-image:auth-backend-test-env-version<version_number>
   - docker push 897722687594.dkr.ecr.eu-west-2.amazonaws.com/hpub-image:auth-backend-test-env-version<version_number>


# Health Publication Backend Folder Structure and Overview

Below is a detailed explanation of the folder structure for the Health Publication Backend application. This Django-based web application leverages Wagtail (a Django-based CMS) to manage and serve various health publication content.

## Top-Level Directory: `backend_alpha`
**Path:** `\hpub-webapp\hpub-backend\backend_alpha`

### Contents:
- **`manage.py`**: The Django management script used to run the server, create database migrations, run tests, etc.
- **`requirements.txt`**: Lists the Python dependencies needed by the project.
- **`pytest.ini`**: Configuration file for the pytest test runner.
- **`README.md`**: Provides an overview, installation instructions, and basic usage information.
- **`.coverage` & `coverage` files**: Generated by test coverage tools, providing coverage statistics for the codebase.
- **`scripts/`**: Contains helper scripts or utilities for deployment, maintenance, or setup.
- **`test/`**: It holds the backend-wide test files.

### Generated Directories:
- **`.pytest_cache/`**: A cache directory generated by pytest.

## Main Subdirectories:
1. **`backend_alpha/`** (Django project module)
2. **`configs/`** (Configuration files and utilities)
3. **`core/`** (Domain logic and apps)

---

## `backend_alpha/backend_alpha/`
**Path:** `hpub-webapp\hpub-backend\backend_alpha\backend_alpha`

This inner folder defines the core Django project module.

### Key Files:
- **`__init__.py`**: Marks the directory as a Python package.
- **`asgi.py`**: ASGI configuration for running the application asynchronously.
- **`settings.py`**: Contains Django settings for installed apps, databases, middleware, etc.
- **`urls.py`**: Main URL dispatcher.
- **`wsgi.py`**: WSGI configuration for production servers.

---

## `backend_alpha/configs/`
**Path:** `\hpub-webapp\hpub-backend\backend_alpha\configs`

Contains configuration-related files and utilities.

### Contents:
- **`__init__.py`**: Marks this as a Python package.
- **`.env.dev` & `.env.example`**: Environment variable files storing credentials and environment-specific configurations.
- **`config.py`**: Parses and loads configurations from environment variables.
- **`get_secret_config.py`**: Helper for managing secret keys or credentials.

### Purpose:
Centralized management of environment variables and configuration parameters for different environments.

---

## `backend_alpha/core/`
**Path:** `hpub-webapp\hpub-backend\backend_alpha\core`

Acts as the main container for the domain logic of the application. Each subdirectory represents a Django “app” or functional module.

### Common Files in Each App:
- **`__init__.py`**: Marks the app as a Python package.
- **`models.py`**: Defines data models for the app.
- **`serializers.py`**: Handles data conversion to/from JSON.
- **`views.py`**: Contains view logic (class-based or function-based views).
- **`urls.py`**: Defines URL patterns for the app.
- **`migrations/`**: Stores database migration files.

### API Subdirectories:
1. **`addresses/`**: Manages user address entities (e.g., recipient addresses for orders).
2. **`audiences/`**: Manages audience segments/ user groups that content (publications) might target..
3. **`customer_support/`**: Handles customer support inquiries.
4. **`diseases/`**: Manages disease-related content, it references conditions, guidelines, or health publications tied to specific diseases..
5. **`errors/`**: Contains custom exceptions or error handling logic.
6. **`establishments/`**: Represents clinics, hospitals, etc.
7. **`feedbacks/`**: Handles user feedback.
8. **`languages/`**: Manages multilingual content delivery.
9. **`order_limits/`**: Defines logic for order quantity limits ensuring users or organizations do not exceed set restrictions. APIs would allow reading or managing those limits.
10. **`orders/`**: Manages the ordering process for health publications. Contains endpoints for placing orders, retrieving order statuses, and handling order-related workflows.
11. **`organizations/`**: Represents organizations managing publications.
12. **`products/`**: Manages health publication entities.
13. **`programs/`**: Handles health programs or campaigns.
14. **`roles/`**: Manages user roles and permissions.
15. **`users/`**: Handles user accounts and authentication.
16. **`utils/`**: Shared utility functions.
17. **`vaccinations/`**: Manages vaccine-related publications.
18. **`where_to_use/`**: Details places where a particular publication can be applied/ where it is intended.




# API Documentation
This is a link to to the published backend api doc: https://documenter.getpostman.com/view/17965993/2sAYBd8Tjr
