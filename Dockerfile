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
# Required system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        cron \
        curl \
        ffmpeg \
        libicu-dev \
        liblzma-dev \
        libmagic1 \
        tzdata \
        xz-utils \
        zlib1g-dev \
    && ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime \
    && echo "$TZ" > /etc/timezone

# Secure download and verify libxml2 (≥ 2.12.10)
WORKDIR /tmp

ENV LIBXML2_VER=2.12.10
ENV LIBXML2_HASH=5cf8d6d6637b7a72d31fc275d27c734ea1f5732d6a2871f0cc05fa0b66a6ef0f

RUN curl --fail --location --proto '=https' --tlsv1.2 \
    -O https://download.gnome.org/sources/libxml2/2.12/libxml2-${LIBXML2_VER}.tar.xz && \
    echo "${LIBXML2_HASH}  libxml2-${LIBXML2_VER}.tar.xz" | sha256sum -c - && \
    tar xf libxml2-${LIBXML2_VER}.tar.xz && \
    cd libxml2-${LIBXML2_VER} && \
    ./configure --prefix=/usr --with-python=no && \
    make -j"$(nproc)" && \
    make install && \
    cd / && rm -rf /tmp/libxml2*

# Remove build dependencies
RUN apt-get purge -y \
        build-essential \
        curl \
        liblzma-dev \
        libicu-dev \
        xz-utils \
        zlib1g-dev \
    && apt-get autoremove -y && apt-get clean && rm -rf /var/lib/apt/lists/*

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

