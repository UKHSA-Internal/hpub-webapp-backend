#!/bin/sh
# Enable strict error handling:
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
migrations_output=$(python manage.py showmigrations --verbosity 2 2>&1) || {
  echo "SHOWMIGRATIONS FAILED:"
  echo "$migrations_output"
  exit 1
}
echo "$migrations_output"

# Debug: output each line numbered to check formatting (optional)
echo "Detailed migration output:"
echo "$migrations_output" | nl

# Step 3: Count pending migrations by searching for pending markers "[ ]"
pending_count=$(echo "$migrations_output" | grep -c "\[ \]")
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
