#!/usr/bin/env bash
# file: entra-duplicates.sh

# Directories
success_dir="files/processed/success/batches"
failed_dir="files/processed/failed/batches"
raw_dir="files/raw/batches"

# Iterate over each file in the success directory
for success_file in "$success_dir"/*; do
    filename=$(basename "$success_file")
    

    # Check in failed directory
    failed_match=$(find "$failed_dir" -maxdepth 1 -type f -name "$filename")
    if [[ -n "$failed_match" ]]; then
        echo "  Found in failed: $failed_match"
    fi

    # Check in raw directory
    raw_match=$(find "$raw_dir" -maxdepth 1 -type f -name "$filename")
    if [[ -n "$raw_match" ]]; then
        echo "  Found in raw: $raw_match"
    fi
done
