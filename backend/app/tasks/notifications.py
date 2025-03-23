# app/tasks/notifications.py
from celery import shared_task
import redis
import json
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=5)
def send_notification(self, user_id, notification_type, action, data):
    """
    Envía una notificación a un usuario específico
    """
    try:
        # Conectar a Redis directamente
        r = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        
        # Verificar si el usuario está conectado
        is_online = r.get(f"user:{user_id}:status") == "online"
        
        # Construir la notificación
        notification = {
            "type": notification_type,
            "action": action,
            "data": data
        }
        
        if is_online:
            # Publicar en el canal del usuario
            channel_name = f"user:{user_id}:notifications"
            message_data = json.dumps(notification)
            result = r.publish(channel_name, message_data)
            
            # Si nadie recibió la publicación, guardar como pendiente
            if result == 0:
                _save_pending_message(r, user_id, notification)
        else:
            # Si no está conectado, guardar como mensaje pendiente
            _save_pending_message(r, user_id, notification)
            
        return True
    
    except Exception as e:
        logger.error(f"Error al enviar notificación: {str(e)}")
        # Reintento con backoff exponencial
        retry_delay = 60 * (2 ** self.request.retries)
        self.retry(exc=e, countdown=retry_delay)

def _save_pending_message(redis_conn, user_id, message):
    """Almacena un mensaje pendiente para entrega posterior"""
    try:
        message_data = json.dumps(message)
        
        # Guardar en lista de pendientes
        redis_conn.lpush(f"user:{user_id}:pending_messages", message_data)
        redis_conn.expire(f"user:{user_id}:pending_messages", 86400 * 7)  # 7 días
        
        # Incrementar contador
        redis_conn.incr(f"user:{user_id}:pending_count")
        redis_conn.expire(f"user:{user_id}:pending_count", 86400 * 7)
        
        logger.info(f"Mensaje guardado para entrega posterior a {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error al guardar mensaje pendiente: {e}")
        return False