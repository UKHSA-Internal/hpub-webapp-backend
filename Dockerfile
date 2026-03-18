# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Create non-root user
RUN adduser --disabled-password --gecos "" appuser

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/London \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies:
# - cron: for scheduled tasks
# - ffmpeg: for video/audio probing
# - libmagic1: MIME detection
# - tzdata: timezone
# - libreoffice: for doc conversions/page counts
# - fonts-dejavu: prevent blank glyphs in PDFs
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        cron \
        ffmpeg \
        libmagic1 \
        tzdata \
        libreoffice-writer libreoffice-core libreoffice-common \
        fonts-dejavu \
    && ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Create app directory
WORKDIR /app


# --- FIX: Ensure safe tmp directory exists ---
# Create a private tmp dir for LibreOffice configs/cache
RUN mkdir -p /app/.lo_tmp && chown -R appuser:appuser /app/.lo_tmp
ENV HOME=/app/.lo_tmp
ENV XDG_CACHE_HOME=/app/.lo_tmp/.cache
ENV XDG_CONFIG_HOME=/app/.lo_tmp/.config


# Copy and install Python dependencies
COPY ./src/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt --verbose

# Copy application code
COPY ./src /app/

# Change ownership (optional)
RUN chown -R appuser:appuser /app

# Copy entrypoint script
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Copy LibreOffice healthcheck script
COPY lo_healthcheck.sh /usr/local/bin/lo_healthcheck.sh
RUN chmod +x /usr/local/bin/lo_healthcheck.sh

# Expose the application port
EXPOSE 8000

# Add Docker HEALTHCHECK (runs every 30s)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD /usr/local/bin/lo_healthcheck.sh || exit 1

# Run as non-root for the app
USER appuser

# Entrypoint: starts cron + Gunicorn (and runs LO startup check)
ENTRYPOINT ["/app/entrypoint.sh"]
