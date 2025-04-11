#!/bin/bash
set -eo pipefail

echo "=============================="
echo "== Starting entrypoint.sh   =="
echo "=============================="



# Step 1: Generate (or update) migration files
echo "=============================="
echo "Running makemigrations..."
makemigrations_output=$(python manage.py makemigrations --verbosity 2 2>&1) || {
  echo "MAKEMIGRATIONS FAILED:"
  echo "$makemigrations_output"
  exit 1
}
echo "$makemigrations_output"

# Step 2: Show migrations status
echo "=============================="
echo "Listing migrations..."
migrations_output=$(python manage.py showmigrations --verbosity --no-color 2 2>&1) || {
  echo "SHOWMIGRATIONS FAILED:"
  echo "$migrations_output"
  exit 1
}
echo "$migrations_output"

# Step 3: Count pending migrations by searching for pending markers "[ ]"
clean_output=$(echo "$migrations_output" | sed 's/\x1B\[[0-9;]*[a-zA-Z]//g')
pending_count=$(echo "$clean_output" | grep -E -c "^\s*\[ \]")
echo "Number of pending migrations: $pending_count"


# Step 4: If there are pending migrations, apply them
if [ "$pending_count" -gt 0 ]; then
  echo "=============================="
  echo "Applying pending migrations..."
  migrate_output=$(python manage.py migrate --verbosity 2 2>&1) || {
    echo "MIGRATE FAILED:"
    echo "$migrate_output"
    exit 1
  }
  echo "$migrate_output"
else
  echo "No pending migrations found. Skipping migrate step."
fi

# Step 5: Start Gunicorn
echo "=============================="
echo "Starting Gunicorn..."
exec gunicorn health_pubs.wsgi:application --bind 0.0.0.0:8000 --timeout 600
