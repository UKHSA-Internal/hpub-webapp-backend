#!/bin/sh
set -e

if command -v soffice >/dev/null 2>&1; then
    echo "✔ LibreOffice available: $(soffice --version 2>/dev/null || echo 'version check failed')"
    exit 0
else
    echo "✘ LibreOffice not found!"
    exit 1
fi
