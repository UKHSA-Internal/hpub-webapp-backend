#!/bin/bash
set +eo pipefail

echo "=============================="
echo "== Starting entrypoint.sh   =="
echo "=============================="
echo "DB USER: $DB_USER"
# -----------------------------------------------------------------------------
# Step 1: List current migration status
# -----------------------------------------------------------------------------
echo "=============================="
echo "Listing migrations..."
migrations_output=$(python manage.py showmigrations --verbosity=2 --no-color 2>&1) || {
  echo "SHOWMIGRATIONS FAILED:"
  echo "$migrations_output"
  exit 1
}
echo "$migrations_output"
# -----------------------------------------------------------------------------
# Step 2: Count pending migrations
# -----------------------------------------------------------------------------
# Remove any ANSI color codes (just in case)
clean_output=$(echo "$migrations_output" | sed 's/\x1B\[[0-9;]*[a-zA-Z]//g')
# Count lines that have the pending migration marker, assuming lines start with optional whitespace then "[ ]"
pending_count=$(echo "$clean_output" | grep -E -c "^\s*\[ \]")
echo "Number of pending migrations: $pending_count"

# -----------------------------------------------------------------------------
# Step 3: Apply pending migrations if needed
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
# Step 4: Start the cron service and schedule the cron jobs
# -----------------------------------------------------------------------------
# ───────────────────────────────────────────────────────────────────────────────
# Schedule: check upcoming drafts at 07:00
# ───────────────────────────────────────────────────────────────────────────────
echo "0 7 * * * root cd /app && python manage.py check_upcoming_drafts \
    >> /var/log/check_upcoming_drafts.log 2>&1" > /etc/cron.d/check_upcoming_drafts
chmod 0644 /etc/cron.d/check_upcoming_drafts
echo "Scheduled: check_upcoming_drafts at 07:00 daily."

# ───────────────────────────────────────────────────────────────────────────────
# Schedule: publish scheduled products at 00:00
# ───────────────────────────────────────────────────────────────────────────────
echo "50 16 * * * root cd /app && python manage.py publish_scheduled_products \
    >> /var/log/publish_scheduled_products.log 2>&1" > /etc/cron.d/publish_scheduled_products
chmod 0644 /etc/cron.d/publish_scheduled_products
echo "Scheduled: publish_scheduled_products at 16:50 GMT daily."

# -----------------------------------------------------------------------------
# Step 5: Start the Gunicorn WSGI server
# -----------------------------------------------------------------------------
echo "=============================="
echo "Starting Gunicorn..."
exec gunicorn health_pubs.wsgi:application --bind 0.0.0.0:8000 --timeout 600
