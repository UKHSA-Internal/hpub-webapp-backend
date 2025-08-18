#!/usr/bin/env bash
# file: entra-upload.sh

# Read token from file
MICROSOFT_ENTRA_UPLOAD_BATCHES_COUNT=312
MICROSOFT_ENTRA_SECRET_ACCESS_TOKEN=$(<config/secrets/entra.txt)

# Ensure processed folders exist
mkdir -p files/interim/responses
mkdir -p files/processed/success/batches
mkdir -p files/processed/failed/batches

batch_count=0

# Loop through JSON batch files
for f in files/raw/batches/*.json; do
    batch_name=$(basename "$f") 
    echo "Uploading $batch_name..."

    # Perform upload and capture HTTP status
    batch_interim_response_file="files/interim/responses/$batch_name"
    batch_http_status=$(curl -s -o "$batch_interim_response_file" -w "%{http_code}" \
        -X POST "https://graph.microsoft.com/v1.0/\$batch" \
        -H "Authorization: Bearer $MICROSOFT_ENTRA_SECRET_ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        --data @"$f")

    if [[ "$batch_http_status" == "401" ]]; then
        echo 'Token Expired'
        exit 1
    fi

    # Check batch-level HTTP status
    if [[ "$batch_http_status" != "200" ]]; then
        echo "$f failed at batch level ($batch_http_status)"
        mv "$f" files/processed/failed/batches/
        exit 1
    fi

    # Check sub-request failures
    failures=$(jq '[.responses[] | select(.status < 200 or .status >= 300)]' $batch_interim_response_file)
    if [ "$(echo "$failures" | jq 'length')" -gt 0 ]; then
        echo "$f had sub-request failures:"
        echo "$failures" | jq -r '.[] | "\(.body.id // "N/A") | Status: \(.status) | Error: \(.body.error.message)"'
        mv "$f" files/processed/failed/batches/
        continue
    fi

    # Move file based on success
    echo "$f completed successfully ($batch_http_status)"
    mv "$f" files/processed/success/batches/
    ((batch_count++))

    # Exit if success goal reached
    if [ "$batch_count" -ge "$MICROSOFT_ENTRA_UPLOAD_BATCHES_COUNT" ]; then
        echo "$MICROSOFT_ENTRA_UPLOAD_BATCHES_COUNT batches uploaded."
        exit 0
    fi
done

echo "Finished processing. Total batches uploaded: $batch_count"
exit 0
