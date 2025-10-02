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


# # -----------------------------------------------------------------------------
# # Step 3a: Ensure django_migrations table exists
# # -----------------------------------------------------------------------------
# echo "Checking if 'django_migrations' table exists…"
# table_check=$(psql -U "$DB_USER" -d "$DB_NAME" -tAc \
#   "SELECT to_regclass('public.django_migrations');")

# if [ "$table_check" = "" ] || [ "$table_check" = "NULL" ]; then
#   echo "'django_migrations' table missing — forcing initial migrate."
#   python manage.py migrate --verbosity=2
# fi


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
# Step 5: Start the cron service and schedule the cron jobs
# -----------------------------------------------------------------------------
# ───────────────────────────────────────────────────────────────────────────────
# Schedule: check upcoming drafts at 07:00
# ───────────────────────────────────────────────────────────────────────────────
echo "0 7 * * * root cd /app && python manage.py check_upcoming_drafts \
    >> /var/log/check_upcoming_drafts.log 2>&1" > /etc/cron.d/check_upcoming_drafts
chmod 0644 /etc/cron.d/check_upcoming_drafts
echo "Scheduled: check_upcoming_drafts at 07:00 daily."

# ───────────────────────────────────────────────────────────────────────────────
# Schedule: publish scheduled products at 16:50 (GMT)
# ───────────────────────────────────────────────────────────────────────────────
echo "50 16 * * * root cd /app && python manage.py publish_scheduled_products \
    >> /var/log/publish_scheduled_products.log 2>&1" > /etc/cron.d/publish_scheduled_products
chmod 0644 /etc/cron.d/publish_scheduled_products
echo "Scheduled: publish_scheduled_products at 16:50 GMT daily."

# -----------------------------------------------------------------------------
# Step 6: Start the Gunicorn WSGI server
# -----------------------------------------------------------------------------
echo "=============================="
echo "Starting Gunicorn…"
exec gunicorn health_pubs.wsgi:application --bind 0.0.0.0:8000 --workers 2 --timeout 600
