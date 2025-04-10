#!/bin/sh
set -e

echo "Checking for pending migrations...."
echo "Listing project files:"
ls -al

MIGRATIONS_OUTPUT=$(python manage.py showmigrations --verbosity 3 2>&1) || {
  echo "SHOWMIGRATIONS FAILED:"
  echo "$MIGRATIONS_OUTPUT"
  exit 1
}

echo "Pending migrations output:"
echo "$MIGRATIONS_OUTPUT"

PENDING_COUNT=$(echo "$MIGRATIONS_OUTPUT" | grep -c "\[ \]")

if [ "$PENDING_COUNT" -gt 0 ]; then
  echo "Applying migrations...."
  python manage.py makemigrations || echo "MAKEMIGRATIONS FAILED"
  python manage.py migrate || echo "MIGRATE FAILED"
else
  echo "No migrations needed.."
fi

echo "Starting Gunicorn..."
exec gunicorn health_pubs.wsgi:application --bind 0.0.0.0:8000 --timeout 600
