# Health Publication Backend API Documentation

## Overview

This project is a Wagtail-Django-based backend application for managing various health publication components such as programs, products(publications), ordering publications, and more. The project uses Wagtail to provide APIs for interacting with these components.


## Environments & Access

The backend supports multiple environments:

* **dev**
* **test**
* **uat**
* **preprod**
* **prod**

### Accessing an Environment

1. Log in to AWS and retrieve your temporary access token.
2. Use this same token consistently for:

   * Accessing the environment via CLI
   * Running the backend locally
   * Accessing the environment's database

### Local Database Access via SSH

To connect to the database locally:

```sh
# Clone infrastructure repository
$ git clone <iac-repo-url>
$ cd hpub-iac/docs/scripts

# Run the database access script
$ ./database_access.sh
```

> Note: You must have already exported your AWS credentials for the specific environment.

## Prerequisites

   Before running the project, ensure that you have the following:

   1. Python (3.10+)
   2. PostgreSQL, Django
   3. Environment variables (.env.dev file)
   2. Generate Environment File (.env)
      Run the following make command to generate the .env file for the desired environment:

      `make env ENV={environment}`

      This will:

      Fetch environment variables from the ECS task definition

      Retrieve secrets from AWS Secrets Manager

      Save everything into health_pubs/configs/.env
   4. pip (Python package manager)
   5. Docker (optional, for running the project in a container)
   6. Install PgAdmin to visualize the db using this Link `https://ftp.postgresql.org/pub/pgadmin/pgadmin4/v8.13/windows/pgadmin4-8.13-x64.exe`
   7. Install and set up Postman to test out the endpoints.
   8. Have access to AWS Environments

## Getting Started

1. Clone Repository
    - `git clone <repository-url>`
    - `cd hpub-webapp-backend/health_pubs`

2. Set Up Environment Variables

   - Create an .env.dev file in the directory `/hpub-webapp-backend/health_pubs/configs/`

   - Ensure you have .env.dev file in the `/backend-alpha/configs/` directory.

3. Install Dependencies
   - `python -m venv venv`
   - `.\venv\Scripts\Activate.ps1`
   - `pip install -r requirements.txt`
4. Activate Your AWS Configuration
   - In your terminal Run `aws configure`
   - Add your secrets-key, access-key and default region = `eu-west-2`

5. Apply Database Migrations(Optional, this is for only if you made changes to the model structure)
   Run the following commands to apply migrations
   - `python manage.py makemigrations`

   - `python manage.py migrate`

6. Start the Development Server
   Start the Django development server with the specified port (optional), If you do not specify a port, the server will run on the default port 8000.
   - `python manage.py runserver <port>`

## Running the Application with Docker

   If you prefer running the application in Docker, follow these steps:

   1. Ensure you have Docker installed on your machine.
   2. Build the Docker image for the project:
      - `docker build -t hpub-webapp-backend .`
   3. Run the Docker container:
      - `docker run -d -p 8000:8000 hpub-webapp-backend`
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


## Backend Deployment Pipeline

This repository contains the CI/CD pipeline for deploying the **Backend Service** using **GitHub Actions** and **AWS ECS**.

### Overview

The pipeline consists of **three main jobs**:

1. **Build & Test** → Builds the container image and runs unit tests.
2. **Release** → Tags and pushes the container image to **Amazon ECR**.
3. **Deploy** → Updates the **ECS task definition** and deploys the latest image.

### Pipeline Workflow

### **1 Build & Test**
This step ensures the application is built correctly and passes unit tests and is triggered on pushes to any branch with an open PR and on pushes to main.

**Steps**:
- Checkout repository
- Set up Python
- Run unit tests (currently non-blocking but will be enforced in the future)
- Build the docker image and if in main, tag the Docker image with a temporary tag
- Push image to Amazon ECR with the temporary tag

### **2 Release**
This step creates and pushes a new image tag for deployment and is only run on a push to main.

**Steps**:
- Checkout repository
- Generate a new release tag
- Pull the temporary tag, retag with semver tag, and push the new tag to ECR

### **3 Deploy**
This step deploys the latest version to AWS ECS. It will only run if the Release step has fun. It automatically runs for all environments (dev, qat, test, prd) if the previous environment deployment was succesful.

**Steps**:
- Update AWS Systems Manager Parameter Store with the latest tag to avoid conflicts with Terraform.
- Update the ECS Task Definition to use the new image URI.
- Updates the container image reference to the new tag in the ECR task definition.
- Deploys the new task definition and checks performs a smoke test. In the future, this will require more extensive end-to-end-testing.

# Health Publication Backend Folder Structure and Overview

Below is a detailed explanation of the folder structure for the Health Publication Backend application. This Django-based web application leverages Wagtail (a Django-based CMS) to manage and serve various health publication content.

## Top-Level Directory: `health_pubs`
**Path:** `\hpub-webapp-backend\health_pubs`

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
1. **`health_pubs/`** (Django project module)
2. **`configs/`** (Configuration files and utilities)
3. **`core/`** (Domain logic and apps)

---

## `health_pubs/health_pubs/`
**Path:** `\hpub-webapp-backend\health_pubs\health_pubs`

This inner folder defines the core Django project module.

### Key Files:
- **`__init__.py`**: Marks the directory as a Python package.
- **`asgi.py`**: ASGI configuration for running the application asynchronously.
- **`settings.py`**: Contains Django settings for installed apps, databases, middleware, etc.
- **`urls.py`**: Main URL dispatcher.
- **`wsgi.py`**: WSGI configuration for production servers.

---

## `health_pubs/configs/`
**Path:** `\hpub-webapp-backend\health_pubs\configs`

Contains configuration-related files and utilities.

### Contents:
- **`__init__.py`**: Marks this as a Python package.
- **`.env.dev` & `.env.example`**: Environment variable files storing credentials and environment-specific configurations.
- **`config.py`**: Parses and loads configurations from environment variables.
- **`get_secret_config.py`**: Helper for managing secret keys or credentials.

### Purpose:
Centralized management of environment variables and configuration parameters for different environments.

---

## `health_pubs/core/`
**Path:** `\hpub-webapp-backend\health_pubs\core`

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

### How To Run Tests:
1. Navigate to the test directory, 
   Open a terminal and run:  
   cd `health_pubs/test/` 
2. Run a specific test file
   Use the following command: 
   `pytest <name_of_test_file> -v`
   Example:
   `pytest test_audiences.py -v`
3. Run all tests in the directory
   If you want to run all tests at once, execute:
   `pytest -v`
4. Run tests with coverage(Optional):
   If you want to check test coverage, install `pytest-cov` using `pip` and run:
   `pytest --cov=health_pubs`


# API Documentation
This is a link to to the published backend api doc: https://documenter.getpostman.com/view/17965993/2sB2qZFhrF


## 🔹 Update User Role via Management Command
After assigning a user to `Admin` status in Azure External Id do the following to update the role of that user in Database:

   ### 📌 Description
   The `update_user_role` management command allows you to change a user's role from **User** (`role_ref_id=1`) to **Admin** (`role_ref_id=8`). This is useful when updating roles via the command line without manually editing the database.
   Please following the steps in the documentation in this link [text](https://github.com/UKHSA-Internal/hpub-aps/blob/main/event_triggers_lambdas/update_user_role/README.md) this process has been turned into a Lambda function in AWS to help for easy use.


## Debugging & Troubleshooting
1. Logs

   - Local: console stdout/stderr

   - EKS/ECS: CloudWatch /ecs/healthpub-backend

2. Error Tracking

   - Sentry DSN in .env → check Sentry dashboard

3. Common Issues

   - Failed migrations → drop and recreate the local DB, re-run migrations

   - Docker build errors → clear cache: docker builder prune

   - AWS permission denied → confirm your IAM role has ecs:*, ssm:GetParameter, ecr:*


## Glossary & References
- Wagtail: Django-based CMS
- ECR: Elastic Container Registry
- ECS: Elastic Container Service
- SSM: AWS Systems Manager Parameter Store
- IAM: AWS Identity and Access Management

