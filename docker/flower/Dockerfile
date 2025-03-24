FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (minimizados para flower)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY ./backend/requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code - flower solo necesita la configuración de celery
COPY ./backend/app/worker.py /app/app/
COPY ./backend/app/core /app/app/core/

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Expose Flower port
EXPOSE 5555

# Run Flower
CMD ["celery", "-A", "app.worker", "flower", "--port=5555", "--address=0.0.0.0"]