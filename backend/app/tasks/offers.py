# app/tasks/offers.py
from celery import shared_task
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import json
import redis
from sqlalchemy import create_engine, text, select, update, and_
from sqlalchemy.orm import sessionmaker, Session
from app.core.config import settings
from app.models.offer import Offer
from app.models.product import Product
from app.models.user import User

logger = logging.getLogger(__name__)

# Conexión a base de datos para tareas de Celery
def get_db_session() -> Session:
    engine = create_engine(str(settings.DATABASE_URL))
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = SessionLocal()
    try:
        return db
    except Exception as e:
        db.close()
        raise e

# Conexión a Redis para tareas de Celery
def get_redis_connection():
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

@shared_task(bind=True, max_retries=5)
def send_notification(self, user_id: str, notification_data: dict):
    """
    Envía una notificación a un usuario a través de Redis para WebSockets.
    Guarda el mensaje como pendiente si el usuario no está conectado.
    """
    try:
        r = get_redis_connection()
        
        # Verificar si el usuario está conectado
        is_online = r.get(f"user:{user_id}:status") == "online"
        
        if is_online:
            # Publicar en canal de usuario
            channel_name = f"user:{user_id}:notifications"
            message_data = json.dumps(notification_data)
            result = r.publish(channel_name, message_data)
            
            # Si nadie recibió la publicación, guardar como pendiente
            if result == 0:
                logger.warning(f"Usuario {user_id} aparece online pero nadie recibió la notificación")
                _save_pending_message(r, user_id, notification_data)
        else:
            # Usuario offline, guardar mensaje pendiente
            _save_pending_message(r, user_id, notification_data)
            
        return True
        
    except Exception as e:
        logger.error(f"Error al enviar notificación: {str(e)}")
        retry_delay = 60 * (2 ** self.request.retries)  # 60s, 120s, 240s, etc.
        raise self.retry(exc=e, countdown=retry_delay)

def _save_pending_message(redis_conn, user_id: str, message: dict):
    """Almacena un mensaje pendiente para entrega posterior"""
    try:
        message_data = json.dumps(message)
        
        # Guardar en lista de mensajes pendientes
        redis_conn.lpush(f"user:{user_id}:pending_messages", message_data)
        
        # Establecer TTL (7 días)
        redis_conn.expire(f"user:{user_id}:pending_messages", 86400 * 7)
        
        # Incrementar contador
        redis_conn.incr(f"user:{user_id}:pending_count")
        redis_conn.expire(f"user:{user_id}:pending_count", 86400 * 7)
        
        logger.info(f"Mensaje guardado para entrega posterior a {user_id}")
        return True
    except Exception as e:
        logger.error(f"Error al guardar mensaje pendiente: {e}")
        return False

@shared_task(bind=True, name="app.tasks.offers.notify_new_offer_task")
def notify_new_offer_task(self, offer_id: str, product_id: str, product_title: str, 
                          buyer_id: str, buyer_name: str, seller_id: str, 
                          amount: float, currency: str, message: Optional[str], 
                          expires_at: str, created_at: str):
    """Tarea Celery para notificar sobre nuevas ofertas"""
    notification_data = {
        "type": "offer",
        "action": "created",
        "data": {
            "id": offer_id,
            "product_id": product_id,
            "product_title": product_title,
            "buyer_id": buyer_id,
            "buyer_name": buyer_name,
            "amount": amount,
            "currency": currency,
            "message": message,
            "expires_at": expires_at,
            "created_at": created_at,
        }
    }
    
    return send_notification.delay(seller_id, notification_data)

@shared_task(bind=True, name="app.tasks.offers.notify_offer_update_task")
def notify_offer_update_task(self, offer_id: str, product_id: str, seller_id: str, 
                             seller_name: str, buyer_id: str, status: str, updated_at: str):
    """Tarea Celery para notificar actualizaciones de ofertas"""
    status_text = "aceptada" if status == "accepted" else "rechazada"
    
    notification_data = {
        "type": "offer",
        "action": status,
        "data": {
            "id": offer_id,
            "product_id": product_id,
            "seller_id": seller_id,
            "seller_name": seller_name,
            "status": status,
            "updated_at": updated_at,
            "message": f"Tu oferta ha sido {status_text}",
        }
    }
    
    return send_notification.delay(buyer_id, notification_data)

@shared_task(bind=True, name="app.tasks.offers.notify_other_buyers_task")
def notify_other_buyers_task(self, product_id: str, buyer_ids: List[str], message: str):
    """Tarea Celery para notificar a otros compradores cuando una oferta es aceptada"""
    notification_data = {
        "type": "product",
        "action": "sold",
        "data": {
            "product_id": product_id,
            "message": message,
        }
    }
    
    results = []
    for buyer_id in buyer_ids:
        result = send_notification.delay(buyer_id, notification_data)
        results.append(result)
    
    return f"Notificaciones enviadas a {len(buyer_ids)} compradores"

@shared_task(bind=True, name="app.tasks.offers.notify_offer_cancelled_task")
def notify_offer_cancelled_task(self, offer_id: str, product_id: str, 
                                buyer_id: str, buyer_name: str, seller_id: str):
    """Tarea Celery para notificar sobre cancelación de ofertas"""
    notification_data = {
        "type": "offer",
        "action": "cancelled",
        "data": {
            "id": offer_id,
            "product_id": product_id,
            "buyer_id": buyer_id,
            "buyer_name": buyer_name,
            "message": "El comprador ha cancelado su oferta",
        }
    }
    
    return send_notification.delay(seller_id, notification_data)

@shared_task(bind=True, name="app.tasks.offers.expire_offers_task")
def expire_offers_task(self):
    """Tarea Celery para marcar ofertas expiradas"""
    db = get_db_session()
    try:
        now = datetime.now(timezone.utc)
        expired_offers = []
        
        # Obtener ofertas pendientes expiradas
        offers_to_expire = db.query(Offer).join(Product).join(
            User, Offer.buyer_id == User.id
        ).filter(
            Offer.status == "pending",
            Offer.expires_at < now
        ).all()
        
        if not offers_to_expire:
            logger.info("No hay ofertas expiradas para procesar")
            return "No hay ofertas expiradas"
        
        # Actualizar estado de ofertas en una transacción
        for offer in offers_to_expire:
            offer.status = "expired"
            offer.updated_at = now
            offer.version += 1
            
            # Construir datos para notificación
            offer_data = {
                "id": offer.id,
                "product_id": offer.product_id,
                "product_title": offer.product.title if offer.product else "Producto eliminado",
                "buyer_id": offer.buyer_id,
                "buyer_name": offer.buyer.full_name if offer.buyer else "Usuario desconocido",
                "seller_id": offer.seller_id,
                "amount": offer.amount,
                "currency": offer.currency,
                "expires_at": offer.expires_at.isoformat(),
                "created_at": offer.created_at.isoformat(),
            }
            expired_offers.append(offer_data)
            
            # Enviar notificaciones asíncronas
            # Notificar al comprador
            buyer_notification = {
                "type": "offer",
                "action": "expired",
                "data": {
                    "id": offer.id,
                    "product_id": offer.product_id,
                    "product_title": offer_data["product_title"],
                    "expires_at": offer.expires_at.isoformat(),
                    "message": "Tu oferta ha expirado"
                }
            }
            send_notification.delay(offer.buyer_id, buyer_notification)
            
            # Notificar al vendedor
            seller_notification = {
                "type": "offer",
                "action": "expired",
                "data": {
                    "id": offer.id,
                    "product_id": offer.product_id,
                    "product_title": offer_data["product_title"],
                    "buyer_name": offer_data["buyer_name"],
                    "amount": offer.amount,
                    "currency": offer.currency,
                    "expires_at": offer.expires_at.isoformat(),
                    "message": "Una oferta ha expirado"
                }
            }
            send_notification.delay(offer.seller_id, seller_notification)
        
        # Confirmar transacción
        db.commit()
        
        logger.info(f"Expiradas {len(expired_offers)} ofertas")
        return f"Expiradas {len(expired_offers)} ofertas"
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error al expirar ofertas: {str(e)}")
        # Reintento con backoff exponencial
        retry_delay = 60 * (2 ** self.request.retries)
        raise self.retry(exc=e, countdown=retry_delay)
    finally:
        db.close()