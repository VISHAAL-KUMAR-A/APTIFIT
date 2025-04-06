#!/bin/bash

# Exit on error
set -e

echo "Starting build process for APTIFIT Django project..."

# Create and activate virtual environment (if not already done)
if [ ! -d "djangoenv" ]; then
    echo "Creating virtual environment..."
    python -m venv djangoenv
fi

# Activate virtual environment - for Unix/Linux
if [[ "$OSTYPE" == "linux-gnu"* || "$OSTYPE" == "darwin"* ]]; then
    echo "Activating virtual environment (Unix/Linux)..."
    source djangoenv/bin/activate
# For Windows (assuming Git Bash or similar)
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    echo "Activating virtual environment (Windows)..."
    source djangoenv/Scripts/activate
fi

# Install/upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# Fix cryptography issue
echo "Fixing cryptography package..."
pip uninstall -y -ryptography 2>/dev/null || true
pip uninstall -y cryptography
pip install cryptography==41.0.7

# Run migrations
echo "Running Django migrations..."
python manage.py makemigrations
python manage.py migrate

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput

# Run tests
echo "Running tests..."
python manage.py test

echo "Build completed successfully!" 