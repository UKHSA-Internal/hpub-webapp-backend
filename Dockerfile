# Use an official Python runtime as a parent image
FROM python:3.11-slim-bookworm

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt update && apt install -y --no-install-recommends \
    libmagic1 \
    && apt clean \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY health_pubs/requirements.txt /app/

# Install packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt --verbose

# Copy the entire project into the container at /app
COPY health_pubs /app/

# Copy entrypoint
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Expose port 8000 for the application
EXPOSE 8000

# Update the ENTRYPOINT to run migrations conditionally and start the application
ENTRYPOINT ["/app/entrypoint.sh"]