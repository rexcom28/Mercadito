FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (minimizados para el scheduler)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY ./backend/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY ./backend /app/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create directory for beat schedule file
RUN mkdir -p /app/celerybeat

# Run Celery beat
CMD ["celery", "-A", "app.worker", "beat", "--loglevel=info", "--schedule=/app/celerybeat/celerybeat-schedule"]