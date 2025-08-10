#!/bin/bash
set +eo pipefail

echo "=============================="
echo "== Starting entrypoint.sh   =="
echo "=============================="
echo "DB USER: $DB_USER"

# -----------------------------------------------------------------------------
# Step 0: Print Wagtail version
# -----------------------------------------------------------------------------
echo "=============================="
wagtail_version=$(python -c "import wagtail; print(wagtail.__version__)")
echo "Wagtail version: $wagtail_version"
echo "=============================="

# -----------------------------------------------------------------------------
# Step 1: Check for migration files under "core" (or sub‐apps) and generate if empty
# -----------------------------------------------------------------------------
echo "=============================="
echo "Checking for existing migration files under 'core/'…"
# Count any files that look like migrations (e.g. 0001_initial.py, etc.)
migration_count=$(find core -type f -path "*/migrations/[0-9]*_*.py" | wc -l)

if [ "$migration_count" -eq 0 ]; then
  echo "No migration files found (besides __init__.py)."
  echo "Running 'makemigrations' to generate them…"
  makemig_output=$(python manage.py makemigrations --verbosity=2 2>&1) || {
    echo "MAKEMIGRATIONS FAILED:"
    echo "$makemig_output"
    exit 1
  }
  echo "$makemig_output"

  # Re‐count after generating
  migration_count=$(find core -type f -path "*/migrations/[0-9]*_*.py" | wc -l)
  if [ "$migration_count" -eq 0 ]; then
    echo "ERROR: Still no migration files after running makemigrations."
    exit 1
  fi

  echo "Generated $migration_count migration file(s)."
else
  echo "Found $migration_count existing migration file(s)."
fi
echo "=============================="

# -----------------------------------------------------------------------------
# Step 2: List current migration status
# -----------------------------------------------------------------------------
echo "Listing migrations…"
migrations_output=$(python manage.py showmigrations --verbosity=2 --no-color 2>&1) || {
  echo "SHOWMIGRATIONS FAILED:"
  echo "$migrations_output"
  exit 1
}
echo "$migrations_output"

# -----------------------------------------------------------------------------
# Step 3: Count pending migrations
# -----------------------------------------------------------------------------
# Strip any ANSI color codes (in case)
clean_output=$(echo "$migrations_output" | sed 's/\x1B\[[0-9;]*[a-zA-Z]//g')
# Count lines marked “[ ]” (not applied yet)
pending_count=$(echo "$clean_output" | grep -E -c "^\s*\[ \]")
echo "Number of pending migrations: $pending_count"

# -----------------------------------------------------------------------------
# Step 4: Apply pending migrations if needed
# -----------------------------------------------------------------------------
if [ "$pending_count" -gt 0 ]; then
  echo "=============================="
  echo "Applying pending migrations…"
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
# Step 5: Verify search stack (extensions, function, indexes)
# -----------------------------------------------------------------------------
echo "Checking search prerequisites (extensions/indexes)…"
if ! python manage.py check_search_ready; then
  echo "Search readiness check failed. Refusing to start."; exit 1
fi


# -----------------------------------------------------------------------------
# Step 6: Start the Gunicorn WSGI server
# -----------------------------------------------------------------------------
echo "=============================="
echo "Starting Gunicorn…"
exec gunicorn health_pubs.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 600
