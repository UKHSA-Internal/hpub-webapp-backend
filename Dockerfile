# Stage 1: Build libxml2
# Use an official Python runtime as a parent image
# Use Bitnami Python 3.12 image
FROM bitnami/python:3.13.5

# Create non-root user
RUN adduser --disabled-password --gecos "" appuser

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/London \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies (cron, ffmpeg for video, libmagic for MIME detection, tzdata),
# set timezone, then clean up to keep image small.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cron \
        ffmpeg \
        libmagic1 \
        tzdata \
    && ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y libxml2

# Create app directory
WORKDIR /app

# Copy and install Python dependencies
COPY health_pubs/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt --verbose

# Copy application code
COPY health_pubs /app/

# Change ownership (optional)
RUN chown -R appuser:appuser /app

# Copy and make the entrypoint script executable
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Run as non-root
USER appuser


# Expose the application port
EXPOSE 8000

# Use the entrypoint to initialize cron jobs and launch Gunicorn
ENTRYPOINT ["/app/entrypoint.sh"]
