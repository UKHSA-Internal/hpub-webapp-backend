# Use an official Python runtime as a parent image
FROM python:3.10

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    libmagic1 \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY backend_alpha/requirements.txt /app/

# Install packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt --verbose

# Copy the entire project into the container at /app
COPY backend_alpha /app/

# Expose port 8000 for the application
EXPOSE 8000

# Update the ENTRYPOINT to run migrations conditionally and start the application
ENTRYPOINT ["sh", "-c", "echo 'Checking for pending migrations...'; if python manage.py showmigrations | grep '\\[ \\]'; then echo 'Applying migrations...'; python manage.py makemigrations && python manage.py migrate; else echo 'No migrations needed.'; fi; exec gunicorn backend_alpha.wsgi:application --bind 0.0.0.0:8000 --timeout 600"]
