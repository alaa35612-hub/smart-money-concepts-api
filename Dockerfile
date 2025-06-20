# Dockerfile for Fly.io deployment
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY . .

# Expose port
EXPOSE 8000

# Start with gunicorn
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app", "--workers", "1"]
