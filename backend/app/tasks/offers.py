import asyncio
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
# from app.db.session import async_session_maker
from app.db.session import AsyncSessionLocal
from app.models.offer import Offer
from app.models.product import Product
from app.models.user import User
from app.websockets.connection import manager

logger = logging.getLogger(__name__)

# Intervalo para el procesamiento de ofertas expiradas (en segundos)
OFFER_EXPIRATION_CHECK_INTERVAL = 300  # 5 minutos

async def expire_offers() -> List[Dict[str, Any]]:
    """
    Marca como expiradas las ofertas que han pasado su fecha de expiración.
    Retorna la lista de ofertas expiradas.
    """
    # Verificar que AsyncSessionLocal esté inicializado
    from app.db.session import AsyncSessionLocal, init_db_connection, _is_initialized
    
    if AsyncSessionLocal is None or not _is_initialized:
        logger.warning("AsyncSessionLocal no está inicializado, inicializando...")
        success = await init_db_connection()
        if not success or AsyncSessionLocal is None:
            logger.error("No se pudo inicializar AsyncSessionLocal")
            return []
    
    now = datetime.now()
    expired_offers = []
    
    async with AsyncSessionLocal() as session:
        # Obtener ofertas pendientes que han expirado
        result = await session.execute(
            select(Offer)
            .options(
                selectinload(Offer.buyer),
                selectinload(Offer.product)
            )
            .where(
                and_(
                    Offer.status == "pending",
                    Offer.expires_at < now
                )
            )
        )
        offers_to_expire = result.scalars().all()
        
        if not offers_to_expire:
            return []
        
        # Actualizar estado en la base de datos (en un solo query)
        offer_ids = [offer.id for offer in offers_to_expire]
        await session.execute(
            update(Offer)
            .where(Offer.id.in_(offer_ids))
            .values(
                status="expired",
                updated_at=now
            )
        )
        
        # Commit la transacción
        await session.commit()
        
        # Procesar notificaciones para cada oferta expirada
        for offer in offers_to_expire:
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
            
            # Notificar al comprador
            await manager.send_personal_message(
                {
                    "type": "offer",
                    "action": "expired",
                    "data": {
                        "id": offer.id,
                        "product_id": offer.product_id,
                        "product_title": offer_data["product_title"],
                        "expires_at": offer.expires_at.isoformat(),
                        "message": "Tu oferta ha expirado"
                    }
                },
                offer.buyer_id
            )
            
            # Notificar al vendedor
            await manager.send_personal_message(
                {
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
                },
                offer.seller_id
            )
    
    logger.info(f"Expiradas {len(expired_offers)} ofertas")
    return expired_offers

async def offer_expiration_task():
    """
    Tarea periódica para procesar ofertas expiradas.
    """
    logger.info("Iniciando tarea de expiración de ofertas")
    
    while True:
        try:
            # Procesar ofertas expiradas
            expired = await expire_offers()
            if expired:
                logger.info(f"Expiradas {len(expired)} ofertas en este ciclo")
            
            # Esperar hasta el próximo ciclo
            await asyncio.sleep(OFFER_EXPIRATION_CHECK_INTERVAL)
        
        except Exception as e:
            logger.error(f"Error en tarea de expiración de ofertas: {str(e)}")
            # Esperamos un poco en caso de error para no saturar logs
            await asyncio.sleep(60)

# Tarea que se iniciará en el evento de inicio de la aplicación
offer_expiration_background_task = None

async def start_offer_expiration_task():
    """
    Inicia la tarea de expiración de ofertas en segundo plano.
    """
    global offer_expiration_background_task
    
    # Asegurarse de que la base de datos está inicializada
    from app.db.session import init_db_connection, _is_initialized
    
    if not _is_initialized:
        logger.info("Inicializando base de datos antes de iniciar tarea de expiración...")
        success = await init_db_connection()
        if not success:
            logger.error("No se pudo inicializar la base de datos para la tarea de expiración")
            return
    
    if offer_expiration_background_task is None:
        offer_expiration_background_task = asyncio.create_task(offer_expiration_task())
        logger.info("Tarea de expiración de ofertas iniciada")

def stop_offer_expiration_task():
    """
    Detiene la tarea de expiración de ofertas.
    """
    global offer_expiration_background_task
    if offer_expiration_background_task is not None:
        offer_expiration_background_task.cancel()
        offer_expiration_background_task = None
        logger.info("Tarea de expiración de ofertas detenida")