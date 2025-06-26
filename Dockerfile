# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Create non-root user
RUN adduser --disabled-password --gecos "" appuser

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Europe/London \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies (cron, ffmpeg for video, libmagic for MIME detection, tzdata),
# set timezone, then clean up to keep image small.
# Set timezone and install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
        cron \
        ffmpeg \
        libmagic1 \
        tzdata \
        curl \
        build-essential \
        zlib1g-dev \
        liblzma-dev \
        libicu-dev \
        xz-utils \
        ca-certificates \
    && ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime \
    && echo "$TZ" > /etc/timezone \
    && curl -LO https://download.gnome.org/sources/libxml2/2.12/libxml2-2.12.10.tar.xz \
    && tar xf libxml2-2.12.10.tar.xz \
    && cd libxml2-2.12.10 \
    && ./configure --prefix=/usr --with-python=no \
    && make -j"$(nproc)" \
    && make install \
    && cd .. \
    && rm -rf libxml2-2.12.10* \
    && apt-get purge -y \
        build-essential \
        curl \
        liblzma-dev \
        zlib1g-dev \
        libicu-dev \
        xz-utils \
    && apt-get autoremove -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

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

