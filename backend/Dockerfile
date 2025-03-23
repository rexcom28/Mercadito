# FROM python:3.11-slim

# WORKDIR /app

# # Instalar dependencias del sistema
# RUN apt-get update && apt-get install -y --no-install-recommends \
#     build-essential \
#     && rm -rf /var/lib/apt/lists/*

# # Copiar requerimientos e instalar dependencias
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt

# # Copiar el código de la aplicación
# COPY . .

# # Exponer el puerto
# EXPOSE 8000

# # Comando para ejecutar la aplicación usando Uvicorn con workers
# CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        python3-dev \
        curl \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . /app/

# Create static directory and download Swagger UI
RUN mkdir -p /app/static
RUN python /app/scripts/download_swagger_ui.py

# Create media directory for uploads
RUN mkdir -p /app/media

EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]