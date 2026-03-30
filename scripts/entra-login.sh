#!/usr/bin/env bash
# file: entra-login.sh

### MICROSOFT_ENTRA_TENANT_ID=
MICROSOFT_ENTRA_SECRET_ACCESS_TOKEN_FILE=config/secrets/entra.txt

az login --tenant ${MICROSOFT_ENTRA_TENANT_ID} --allow-no-subscriptions
MICROSOFT_ENTRA_SECRET_ACCESS_TOKEN=$(az account get-access-token --resource https://graph.microsoft.com/ --query accessToken -o tsv)
echo "$MICROSOFT_ENTRA_SECRET_ACCESS_TOKEN" > ${MICROSOFT_ENTRA_SECRET_ACCESS_TOKEN_FILE}

echo 'Successfully logged in.'