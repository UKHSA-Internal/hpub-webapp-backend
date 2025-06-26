# Use an official Python runtime as a parent image
FROM python:3.12-alpine

# Create non-root user
RUN addgroup -S appgroup && adduser -S appuser -G appgroup

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/London \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies (cron, ffmpeg for video, libmagic for MIME detection, tzdata),
# set timezone, then clean up to keep image small.
# Set timezone and install dependencies
# Install dependencies and set timezone
RUN apk add --no-cache \
        tzdata \
        ffmpeg \
        file \
        curl \
        build-base \
        zlib-dev \
        xz \
        libxml2-dev \
        libxslt-dev \
        icu-dev \
        bash \
    && cp /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo "$TZ" > /etc/timezone

RUN apk add --no-cache cmake protobuf-dev

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

