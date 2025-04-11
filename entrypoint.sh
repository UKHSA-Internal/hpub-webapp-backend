#!/bin/bash
set -eo pipefail

echo "=============================="
echo "== Starting entrypoint.sh   =="
echo "=============================="


# -----------------------------------------------------------------------------
# Step 2: List current migration status
# -----------------------------------------------------------------------------
echo "=============================="
echo "Listing migrations..."
migrations_output=$(python manage.py showmigrations --verbosity=2 --no-color 2>&1) || {
  echo "SHOWMIGRATIONS FAILED:"
  echo "$migrations_output"
  exit 1
}
echo "$migrations_output"
echo "DB USER: $DB_USER"

# -----------------------------------------------------------------------------
# Step 3: Count pending migrations
# -----------------------------------------------------------------------------
# Remove any ANSI color codes (just in case)
clean_output=$(echo "$migrations_output" | sed 's/\x1B\[[0-9;]*[a-zA-Z]//g')
# Count lines that have the pending migration marker, assuming lines start with optional whitespace then "[ ]"
pending_count=$(echo "$clean_output" | grep -E -c "^\s*\[ \]")
echo "Number of pending migrations: $pending_count"

# -----------------------------------------------------------------------------
# Step 4: Apply pending migrations if needed
# -----------------------------------------------------------------------------
if [ "$pending_count" -gt 0 ]; then
  echo "=============================="
  echo "Applying pending migrations..."
  migrate_output=$(python manage.py migrate --verbosity=2 2>&1) || {
    echo "MIGRATE FAILED:"
    echo "$migrate_output"
    exit 1
  }
  echo "$migrate_output"
else
  echo "No pending migrations found. Skipping migrate step."
fi

# -----------------------------------------------------------------------------
# Step 5: Start the Gunicorn WSGI server
# -----------------------------------------------------------------------------
echo "=============================="
echo "Starting Gunicorn..."
exec gunicorn health_pubs.wsgi:application --bind 0.0.0.0:8000 --timeout 600
