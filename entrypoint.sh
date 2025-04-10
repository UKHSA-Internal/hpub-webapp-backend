#!/bin/sh
set -e

echo "Checking for pending migrations...."

PENDING=$(python manage.py showmigrations --verbosity 3 | grep -c "\[ \]")
echo "$PENDING"
if [ "$PENDING" -gt 0 ]; then
  echo "Applying migrations...."
  python manage.py makemigrations
  python manage.py migrate
else
  echo "No migrations needed.."
fi

echo "Starting Gunicorn..."
exec gunicorn health_pubs.wsgi:application --bind 0.0.0.0:8000 --timeout 600
