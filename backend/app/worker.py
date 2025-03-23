# app/worker.py
from celery import Celery
from app.core.config import settings

celery = Celery(
    "marketplace",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.tasks.notifications", "app.tasks.offers"]
)

# Configuración
celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutos máximo por tarea
    worker_max_tasks_per_child=1000,
    # Configuración de reintentos
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=60,  # 1 minuto entre reintentos
    task_max_retries=3  # Máximo 3 reintentos
)

# Tareas periódicas
celery.conf.beat_schedule = {
    'expire-offers-every-5-minutes': {
        'task': 'app.tasks.offers.expire_offers_task',
        'schedule': 300.0,  # 5 minutos
    }
}