#!/bin/sh
set -e  # Exit on any error

echo "Checking for pending migrations..."
if python manage.py showmigrations | grep '\[ \]'; then
  echo "Applying migrations..."
  python manage.py migrate
else
  python manage.py migrate --check  # temporary
  echo "No migrations needed."
fi

echo "Starting Gunicorn..."
exec gunicorn health_pubs.wsgi:application --bind 0.0.0.0:8000 --timeout 600
