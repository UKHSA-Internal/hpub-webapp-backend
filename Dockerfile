# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/London \
    DEBIAN_FRONTEND=noninteractive

# Install only what we need (cron + tzdata), in Europe/London without prompts,
# then clean up to keep the image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends cron libmagic-dev libmagic1 tzdata \
    && ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY health_pubs/requirements.txt /app/

# Install packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt --verbose

# Copy the entire project into the container at /app
COPY health_pubs /app/

# Copy entrypoint script and make it executable
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Expose port 8000 for the application
EXPOSE 8000

# Use the entrypoint to start cron & gunicorn
ENTRYPOINT ["/app/entrypoint.sh"]
# ENTRYPOINT ["sh", "-c", "echo 'Checking for pending migrations...'; if python manage.py showmigrations | grep '\\[ \\]'; then echo 'Applying migrations...'; python manage.py makemigrations && python manage.py migrate; else echo 'No migrations needed.'; fi; exec gunicorn health_pubs.wsgi:application --bind 0.0.0.0:8000 --timeout 600"]
