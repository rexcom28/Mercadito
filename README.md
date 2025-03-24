# Estructura Docker para Marketplace en Tiempo Real

## Organización de Dockerfiles

La aplicación está separada en diferentes servicios, cada uno con su propio Dockerfile optimizado:

### 1. API (FastAPI)
- **Ubicación**: `./docker/api/Dockerfile`
- **Responsabilidad**: Ejecutar la API REST de FastAPI y gestionar WebSockets
- **Optimizaciones**: Incluye configuración para Swagger UI y archivos estáticos

### 2. Celery Worker
- **Ubicación**: `./docker/worker/Dockerfile`
- **Responsabilidad**: Procesar tareas asíncronas en segundo plano
- **Optimizaciones**: Configuración mínima necesaria para ejecutar workers

### 3. Celery Beat
- **Ubicación**: `./docker/beat/Dockerfile`
- **Responsabilidad**: Programar tareas periódicas (como expiración de ofertas)
- **Optimizaciones**: Incluye volumen para el archivo de programación

### 4. Flower
- **Ubicación**: `./docker/flower/Dockerfile`
- **Responsabilidad**: Proporcionar un panel de monitoreo para Celery
- **Optimizaciones**: Sólo copia los archivos necesarios para Celery

## Volúmenes

El sistema utiliza varios volúmenes para datos persistentes:

- `postgres_data`: Almacenamiento de la base de datos
- `redis_data`: Datos de Redis para caché, broker y pubsub
- `celery_beat_data`: Archivo de programación para Celery beat

## Redes

Todos los servicios están conectados a través de la red `app-network`, lo que permite la comunicación entre contenedores usando los nombres de servicio como nombres de host.

## Cómo ejecutar

```bash
# Iniciar todos los servicios
docker-compose up

# Iniciar todos los servicios en segundo plano
docker-compose up -d

# Iniciar servicios específicos
docker-compose up api celery-worker

# Escalar workers
docker-compose up --scale celery-worker=3

# Reconstruir imágenes
docker-compose build
```

## Acceso a los servicios

- **API**: http://localhost:8000
- **Swagger UI**: http://localhost:8000/docs
- **Flower Dashboard**: http://localhost:5555