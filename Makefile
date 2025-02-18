AWS_REGION=eu-west-2

ENV_FILE=health_pubs/configs/.env

ENV ?=
PROFILE ?=

FRONTEND_SECRETS = \
    VITE_APP_PORT=hpub_frontend_app_port \
    VITE_API_TARGET=hpub_api_target \
    VITE_MSAL_REDIRECT_URI=hpub_azure_b2c_redirect_uri \
    VITE_MSAL_POST_LOGOUT_REDIRECT_URI=hpub_azure_b2c_postlogout_redirect_uri \
    VITE_MSAL_LOGIN_REQUEST_SCOPES=hpub_azure_b2c_scopes \
    VITE_API_BASE_URL=hpub_frontend_base_url

BACKEND_SECRETS = \
    APS_API_KEY=aw-hpub-euw2-$(ENV)-secret-aps_api_key \
    OS_ADDRESS_VERIFICATION_API_KEY=aw-hpub-euw2-$(ENV)-secret-os_address_verification_api_key \
    OS_ADDRESS_VERIFICATION_CLIENT_ID=aw-hpub-euw2-$(ENV)-secret-os_address_verification_client_id \
    OS_ADDRESS_VERIFICATION_CLIENT_SCOPE=aw-hpub-euw2-$(ENV)-secret-os_address_verification_client_scope \
    RELATIVE_PATH=hpub-webapp/hpub-backend/ \
    GOV_UK_NOTIFY_EMAIL_TEMPLATE_ID=aw-hpub-euw2-$(ENV)-secret-gov_uk_notify_email_template_id \
    GOV_UK_NOTIFY_SMS_TEMPLATE_ID=aw-hpub-euw2-$(ENV)-secret-gov_uk_notify_sms_template_id \
    GOV_UK_NOTIFY_API_URL=aw-hpub-euw2-$(ENV)-secret-gov_uk_notify_api_url \
    GOV_UK_NOTIFY_API_KEY=aw-hpub-euw2-$(ENV)-secret-gov_uk_notify_api_key \
    APS_TEST_BASE_URL=aw-hpub-euw2-$(ENV)-secret-aps_test_base_url \
    OS_ADDRESS_VERIFICATION_BASE_URL=aw-hpub-euw2-$(ENV)-secret-os_address_verification_base_url \
    OS_ADDRESS_VERIFICATION_TOKEN_URL=aw-hpub-euw2-$(ENV)-secret-os_address_verification_token_url \
    CONTACT_US_APS_EMAIL_ADDRESS=aw-hpub-euw2-$(ENV)-secret-contact_us_aps_email_address \
    CONTACT_US_TEMPLATE_ID=aw-hpub-euw2-$(ENV)-secret-contact_us_template_id \
    AZURE_B2C_CLIENT_ID=aw-hpub-euw2-$(ENV)-secret-azure_b2c_client_id \
    AZURE_B2C_CLIENT_SECRET_ID=aw-hpub-euw2-$(ENV)-secret-azure_b2c_client_secret_id \
    AZURE_B2C_TENANT_ID=aw-hpub-euw2-$(ENV)-secret-azure_b2c_tenant_id \
    AZURE_B2C_TENANT_NAME=aw-hpub-euw2-$(ENV)-secret-azure_b2c_tenant_name \
    AZURE_B2C_POLICY_NAME=aw-hpub-euw2-$(ENV)-secret-azure_b2c_policy_name \
    AZURE_B2C_JWKS_URI=aw-hpub-euw2-$(ENV)-secret-azure_b2c_jwks_uri \
    DJANGO_SECRET_KEY=aw-hpub-euw2-$(ENV)-secret-django_secret_key \
    AZURE_B2C_ISSUER=aw-hpub-euw2-$(ENV)-secret-azure_b2c_issuer \
    HPUB_FRONTEND_URL=aw-hpub-euw2-$(ENV)-secret-hpub_frontend_url \
    HPUB_EVENT_BRIDGE_SOURCE=aw-hpub-euw2-$(ENV)-secret-hpub_event_bridge_source \
    HPUB_EVENT_BRIDGE_BUS_NAME=aw-hpub-euw2-$(ENV)-secret-hpub_event_bridge_bus_name \
    HPUB_EVENT_BRIDGE_DETAIL_TYPE_ORDER_CREATION=aw-hpub-euw2-$(ENV)-secret-hpub_event_bridge_detail_type_order_creation \
    HPUB_EVENT_BRIDGE_DETAIL_TYPE_PRODUCT_DRAFT=aw-hpub-euw2-$(ENV)-secret-hpub_event_bridge_detail_type_product_draft \
    HPUB_EVENT_BRIDGE_DETAIL_TYPE_PRODUCT_ARCHIVE=aw-hpub-euw2-$(ENV)-secret-hpub_event_bridge_detail_type_product_archive \
    HPUB_EVENT_BRIDGE_DETAIL_TYPE_PRODUCT_WITHDRAWN=aw-hpub-euw2-$(ENV)-secret-hpub_event_bridge_detail_type_product_withdrawn \
    HPUB_EVENT_BRIDGE_DETAIL_TYPE_PRODUCT_LIVE=aw-hpub-euw2-$(ENV)-secret-hpub_event_bridge-detail-type-product_live \
    RSA_KEYS_SECRET_ID=aw-hpub-euw2-$(ENV)-secret-hpub_rsa_keys \
    REDIS_SECRET_VALUE=aw-hpub-euw2-$(ENV)-redis_secret_value \
    HPUB_DATABASE_CREDENTIALS=aw-hpub-euw2-$(ENV)-database_credentials

SECRETS = $(BACKEND_SECRETS) $(FRONTEND_SECRETS)

.PHONY: secrets

secrets:
	@if [ -z "$(ENV)" ] || [ -z "$(PROFILE)" ]; then \
		echo "Error: ENV and PROFILE must be specified"; \
		exit 1; \
	fi
	@echo "Fetching secrets from AWS Secrets Manager for environment: $(ENV) with profile: $(PROFILE)..."
	@rm -f $(ENV_FILE)
	@touch $(ENV_FILE)
	@for secret in $(SECRETS); do \
		key=$$(echo "$$secret" | cut -d= -f1); \
		secret_id=$$(echo "$$secret" | cut -d= -f2); \
		is_frontend_secret=false; \
		for fs in $(FRONTEND_SECRETS); do \
			if [ "$$secret" = "$$fs" ]; then \
				is_frontend_secret=true; \
				break; \
			fi; \
		done; \
		if $$is_frontend_secret; then \
			echo "$$key=$$secret_id" >> $(ENV_FILE); \
			echo "Successfully added $$key to $(ENV_FILE) from local"; \
		elif [ "$$key" = "RSA_KEYS_SECRET_ID" ]; then \
			private_key="$$(aws secretsmanager get-secret-value --region $(AWS_REGION) --profile $(PROFILE) --secret-id $$secret_id --query 'SecretString' --output text | jq -r '.RSA_PRIVATE_KEY')" ; \
			public_key="$$(aws secretsmanager get-secret-value --region $(AWS_REGION) --profile $(PROFILE) --secret-id $$secret_id --query 'SecretString' --output text | jq -r '.RSA_PUBLIC_KEY')" ; \
			echo "RSA_PRIVATE_KEY=\"$$private_key\"" >> $(ENV_FILE); \
			echo "RSA_PUBLIC_KEY=\"$$public_key\"" >> $(ENV_FILE); \
		elif [ "$$key" = "HPUB_DATABASE_CREDENTIALS" ]; then \
			db_name="$$(aws secretsmanager get-secret-value --region $(AWS_REGION) --profile $(PROFILE) --secret-id $$secret_id --query 'SecretString' --output text | jq -r '.DB_NAME')" ; \
			db_host="$$(aws secretsmanager get-secret-value --region $(AWS_REGION) --profile $(PROFILE) --secret-id $$secret_id --query 'SecretString' --output text | jq -r '.DB_HOST')" ; \
			db_user="$$(aws secretsmanager get-secret-value --region $(AWS_REGION) --profile $(PROFILE) --secret-id $$secret_id --query 'SecretString' --output text | jq -r '.DB_USER')" ; \
			db_password="$$(aws secretsmanager get-secret-value --region $(AWS_REGION) --profile $(PROFILE) --secret-id $$secret_id --query 'SecretString' --output text | jq -r '.DB_PASSWORD')" ; \
			db_port="$$(aws secretsmanager get-secret-value --region $(AWS_REGION) --profile $(PROFILE) --secret-id $$secret_id --query 'SecretString' --output text | jq -r '.DB_PORT')" ; \
			echo "DB_NAME=$$db_name" >> $(ENV_FILE); \
			echo "DB_HOST=$$db_host" >> $(ENV_FILE); \
			echo "DB_USER=$$db_user" >> $(ENV_FILE); \
			echo "DB_PASSWORD=$$db_password" >> $(ENV_FILE); \
			echo "DB_PORT=$$db_port" >> $(ENV_FILE); \
		else \
			value="$$(aws secretsmanager get-secret-value --region $(AWS_REGION) --profile $(PROFILE) --secret-id $$secret_id --query 'SecretString' --output text | jq -r 'to_entries[] | .value')" ; \
			if [ "$$value" != "null" ]; then \
				echo "$$key=$$value" >> $(ENV_FILE); \
				echo "Successfully added $$key to $(ENV_FILE)"; \
			else \
				echo "Failed to retrieve secret for $$key"; \
			fi; \
		fi; \
	done
	@echo "Secrets have been written to $(ENV_FILE)"

# Usage: make secrets ENV=dev PROFILE=your-aws-profile