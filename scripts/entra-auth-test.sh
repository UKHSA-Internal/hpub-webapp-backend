
MICROSOFT_ENTRA_SECRET_ACCESS_TOKEN=$(<config/secrets/entra.txt)

curl -H "Authorization: Bearer $MICROSOFT_ENTRA_SECRET_ACCESS_TOKEN" \
     https://graph.microsoft.com/v1.0/me