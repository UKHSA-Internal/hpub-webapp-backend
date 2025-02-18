ENV ?= dev
ENV_FILE=health_pubs/configs/.env

ECS_CLUSTER=aw-hpub-euw2-$(ENV)-ecscluster
ECS_SERVICE=aw-hpub-euw2-$(ENV)-ecssvc-backend

.PHONY: env
env: clean fetch_env_vars fetch_secrets
	@echo "${ENV_FILE} env file created"

.PHONY: fetch_env_vars
fetch_env_vars:
	@echo "# Auto-generated .env file" > ${ENV_FILE}
	@echo "# Environment Variables from ECS Service" >> ${ENV_FILE}
	@TASK_DEF=$$(aws ecs describe-services --cluster $(ECS_CLUSTER) --services $(ECS_SERVICE) \
		--query 'services[0].taskDefinition' --output text); \
	TASK_DEF_ARN=$$(aws ecs describe-task-definition --task-definition $$TASK_DEF \
		--query 'taskDefinition.taskDefinitionArn' --output text); \
	aws ecs describe-task-definition --task-definition $$TASK_DEF_ARN \
		--query 'taskDefinition.containerDefinitions[0].environment' --output json | \
		jq -r '.[] | "\(.name)=\(.value)"' >> ${ENV_FILE}
	@echo "Environment variables pulled from ECS"

.PHONY: fetch_secrets
# Ref line 36-43: if the secret name ends wih ::, it means it's a JSON secret and we want to get the value from the K/V pair.
# Apologies for the horrible way of doing this. BSD/GNU tools have enough differences to make it annoying to do with sed.
fetch_secrets:
	@echo "# Secrets from AWS Secrets Manager" >> ${ENV_FILE}
	@TASK_DEF=$$(aws ecs describe-services --cluster $(ECS_CLUSTER) --services $(ECS_SERVICE) \
		--query 'services[0].taskDefinition' --output text); \
	TASK_DEF_ARN=$$(aws ecs describe-task-definition --task-definition $$TASK_DEF \
		--query 'taskDefinition.taskDefinitionArn' --output text); \
	aws ecs describe-task-definition --task-definition $$TASK_DEF_ARN \
		--query 'taskDefinition.containerDefinitions[0].secrets' --output json | \
		jq -r '.[] | "\(.name)=\(.valueFrom)"' | while read secret; do \
		SECRET_NAME=$$(echo $$secret | cut -d '=' -f2); \
		SECRET_KEY=$$(echo $$secret | cut -d '=' -f1); \
		if [[ "$$SECRET_NAME" == *:: ]]; then \
			IFS=':' read -ra SECRET_ARRAY <<< "$$SECRET_NAME"; \
			SECRET_ID=$$(echo $${SECRET_ARRAY[6]} | rev | cut -c 8- | rev); \
			KEY_NAME=$$(echo $${SECRET_ARRAY[7]} | rev | cut -c 1- | rev); \
			SECRET_VALUE=$$(aws secretsmanager get-secret-value --secret-id $$SECRET_ID \
				--query SecretString --output text | jq -r ".$$KEY_NAME"); \
		else \
			SECRET_VALUE=$$(aws secretsmanager get-secret-value --secret-id $$SECRET_NAME \
				--query SecretString --output text); \
		fi; \
		echo "$$SECRET_KEY=$$SECRET_VALUE" >> ${ENV_FILE}; \
	done
	@echo "Secrets pulled from Secrets Manager"

.PHONY: clean
clean:
	rm -f ${ENV_FILE}
	@echo "${ENV_FILE} file removed"
