from fastapi import APIRouter, Body, Depends, HTTPException, status, Query, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import Any, List, Optional
from datetime import datetime, timedelta, timezone
from app.core.utils import normalize_datetime_comparison 
import uuid
import logging

from app.api import deps
from app.schemas.offer import OfferCreate, OfferResponse, OfferUpdate
from app.models.offer import Offer
from app.models.product import Product
from app.models.user import User
from app.websockets.connection import manager
from app.core.config import settings
from sqlalchemy.exc import IntegrityError
from contextlib import contextmanager
@contextmanager
def transaction_scope(db: Session):
    """Proporciona un contexto transaccional."""
    try:
        yield
        db.commit()
    except IntegrityError as e:
        db.rollback()
        logger.error(f"Error de integridad en transacción: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error de integridad en la operación. Por favor, inténtalo de nuevo."
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error en transacción: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor durante la transacción"
        )

logger = logging.getLogger(__name__)

router = APIRouter()

@router.post("/", response_model=OfferResponse, status_code=status.HTTP_201_CREATED)
async def create_offer(
    *,
    db: Session = Depends(deps.get_db),
    offer_in: OfferCreate,
    current_user: User = Depends(deps.get_current_user),
    background_tasks: BackgroundTasks,
) -> Any:
    """
    Crear una nueva oferta para un producto.
    """
    # Verificar que el producto existe y está activo
    product = db.query(Product).filter(
        Product.id == offer_in.product_id,
        Product.status == "active"
    ).first()
    
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado o no disponible",
        )
    
    # No permitir ofertas al propio producto
    if product.seller_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes ofertar por tu propio producto",
        )
    
    # Validar que no exista otra oferta pendiente del mismo usuario para este producto
    existing_offer = db.query(Offer).filter(
        Offer.product_id == offer_in.product_id,
        Offer.buyer_id == current_user.id,
        Offer.status == "pending"
    ).first()
    
    if existing_offer:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya tienes una oferta pendiente para este producto",
        )
    
    # Crear la oferta con una expiración de 24 horas
    expires_at = datetime.now() + timedelta(days=1)
    
    db_offer = Offer(
        product_id=offer_in.product_id,
        buyer_id=current_user.id,
        seller_id=product.seller_id,
        amount=offer_in.amount,
        currency=product.currency,  # Usar la misma moneda que el producto
        message=offer_in.message,
        expires_at=expires_at,
        version=1,  # Versión inicial para control de concurrencia
    )
    
    db.add(db_offer)
    db.commit()
    db.refresh(db_offer)
    
    # Notificar al vendedor a través de WebSockets (en segundo plano)
    background_tasks.add_task(
        notify_new_offer,
        db_offer.id,
        db_offer.product_id,
        product.title,
        db_offer.buyer_id,
        current_user.full_name,
        db_offer.seller_id,
        db_offer.amount,
        db_offer.currency,
        db_offer.message,
        db_offer.expires_at.isoformat(),
        db_offer.created_at.isoformat(),
    )
    
    return db_offer

async def notify_new_offer(
    offer_id: str,
    product_id: str,
    product_title: str,
    buyer_id: str,
    buyer_name: str,
    seller_id: str,
    amount: float,
    currency: str,
    message: Optional[str],
    expires_at: str,
    created_at: str,
):
    """
    Función de notificación en segundo plano para nuevas ofertas.
    """
    await manager.send_personal_message(
        {
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
        },
        seller_id
    )

@router.get("/", response_model=List[OfferResponse])
def get_offers(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
    role: str = Query(..., description="Rol: 'buyer' para ofertas realizadas, 'seller' para ofertas recibidas"),
    status: Optional[str] = Query(None, description="Estado de la oferta (pending, accepted, rejected, expired)"),
    product_id: Optional[str] = Query(None, description="ID del producto"),
) -> Any:
    """
    Obtener lista de ofertas con filtros.
    """
    query = db.query(Offer)
    
    # Filtrar por rol (comprador o vendedor)
    if role == "buyer":
        query = query.filter(Offer.buyer_id == current_user.id)
    elif role == "seller":
        query = query.filter(Offer.seller_id == current_user.id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El parámetro 'role' debe ser 'buyer' o 'seller'",
        )
    
    # Aplicar filtros adicionales
    if status:
        query = query.filter(Offer.status == status)
    
    if product_id:
        query = query.filter(Offer.product_id == product_id)
    
    # Ordenar por fecha de creación (más recientes primero)
    query = query.order_by(Offer.created_at.desc())
    
    offers = query.all()
    
    # Verificar si hay ofertas cercanas a expirar (menos de 6 horas)
    now = datetime.now(timezone.utc)
    for offer in offers:
        if offer.status == "pending" and offer.expires_at:
            time_left = (offer.expires_at - now).total_seconds() / 3600
            setattr(offer, "hours_left", round(time_left, 1))
            setattr(offer, "expires_soon", time_left < 6)
    
    return offers

@router.get("/{offer_id}", response_model=OfferResponse)
def get_offer(
    *,
    db: Session = Depends(deps.get_db),
    offer_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Obtener una oferta por su ID.
    """
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Oferta no encontrada",
        )
    
    # Verificar que el usuario sea el comprador o el vendedor
    if offer.buyer_id != current_user.id and offer.seller_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver esta oferta",
        )
    
    # Verificar si la oferta está cercana a expirar
    if offer.status == "pending" and offer.expires_at:
        now = datetime.now()
        time_left = (offer.expires_at - now).total_seconds() / 3600
        setattr(offer, "hours_left", round(time_left, 1))
        setattr(offer, "expires_soon", time_left < 6)
    
    return offer

@router.patch("/{offer_id}/respond", response_model=OfferResponse)
async def update_offer_status_via_body(
    *,
    db: Session = Depends(deps.get_db),
    offer_id: str,
    offer_update: OfferUpdate,  # Recibe los datos en el cuerpo del request
    current_user: User = Depends(deps.get_current_user),
    background_tasks: BackgroundTasks,
) -> Any:
    """
    Actualizar el estado de una oferta (aceptar o rechazar) con control de concurrencia optimista.
    Este endpoint requiere un cuerpo JSON con:
    - status: "accepted" o "rejected"
    - version: número de versión actual de la oferta

    Ejemplo:
    ```
    {
        "status": "accepted",
        "version": 1
    }
    ```
    """
    # Extraer status y version del cuerpo del request
    status_value = offer_update.status
    version = offer_update.version
    
    # Verificar que el estado sea válido
    if status_value not in ["accepted", "rejected"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El estado debe ser 'accepted' o 'rejected'",
        )
    
    # Obtener la oferta con bloqueo pesimista para la transacción
    offer = db.query(Offer).filter(Offer.id == offer_id).with_for_update().first()
    if not offer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Oferta no encontrada",
        )
    
    # Verificar versión para control de concurrencia optimista
    if offer.version != version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La oferta ha sido modificada. Versión actual: {offer.version}. Recarga y vuelve a intentar.",
        )
    
    # Verificar que el usuario sea el vendedor
    if offer.seller_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el vendedor puede actualizar el estado de la oferta",
        )
    
    # Verificar que la oferta esté pendiente
    if offer.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede actualizar una oferta con estado '{offer.status}'",
        )
    
    now = datetime.now(timezone.utc)  # Usar siempre UTC para el tiempo actual
    expires_at = offer.expires_at

    # Normalizar las fechas para comparación
    now, expires_at = normalize_datetime_comparison(now, expires_at)

    if expires_at < now:
        # Actualizar a expirada
        offer.status = "expired"
        offer.updated_at = datetime.now(timezone.utc)  # Usar siempre UTC
        offer.version += 1
        db.add(offer)
        db.commit()
        
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La oferta ha expirado",
        )
    
    try:
        # Usar un contexto de transacción explícito
        with transaction_scope(db):
            # Actualizar el estado de la oferta
            offer.status = status_value
            offer.updated_at = datetime.now(timezone.utc)  # Usar UTC
            offer.version += 1
            db.add(offer)
            
            # Si la oferta fue aceptada, marcar el producto como vendido
            product = None
            other_offers = []
            
            if status_value == "accepted":
                # Siempre usar with_for_update() para bloqueo
                product = db.query(Product).filter(
                    Product.id == offer.product_id
                ).with_for_update().first()
                
                if not product:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="Producto no encontrado"
                    )
                    
                # Verificar que el producto siga disponible
                if product.status != "active":
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="El producto ya no está disponible",
                    )
                
                # Marcar como vendido
                product.status = "sold"
                db.add(product)
                
                # Obtener otras ofertas pendientes para rechazarlas
                other_offers = db.query(Offer).filter(
                    Offer.product_id == offer.product_id,
                    Offer.id != offer_id,
                    Offer.status == "pending"
                ).with_for_update().all()  # Usar with_for_update() aquí también
                
                # Rechazar otras ofertas
                for other_offer in other_offers:
                    other_offer.status = "rejected"
                    other_offer.updated_at = datetime.now(timezone.utc)  # Usar UTC
                    other_offer.version += 1
                    db.add(other_offer)
        
        # Refrescar oferta fuera de la transacción
        db.refresh(offer)
        
        # Notificar al comprador sobre la actualización (en segundo plano)
        background_tasks.add_task(
            notify_offer_update,
            offer.id,
            offer.product_id,
            offer.seller_id,
            current_user.full_name,
            offer.buyer_id,
            status_value,
            offer.updated_at.isoformat(),
        )
        
        # Si se aceptó la oferta, notificar a otros compradores (en segundo plano)
        if status_value == "accepted" and other_offers:
            buyer_ids = [o.buyer_id for o in other_offers]
            background_tasks.add_task(
                notify_other_buyers,
                offer.product_id,
                buyer_ids,
                "El producto ha sido vendido a otro comprador",
            )
        
        return offer
    
    except IntegrityError as e:
        db.rollback()
        logger.error(f"Error de integridad al actualizar oferta: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Error al actualizar la oferta. Por favor, inténtalo de nuevo.",
        )
    except Exception as e:
        db.rollback()
        logger.error(f"Error al actualizar oferta: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor",
        )

async def notify_offer_update(
    offer_id: str,
    product_id: str,
    seller_id: str,
    seller_name: str,
    buyer_id: str,
    status: str,
    updated_at: str,
):
    """
    Función para notificar al comprador sobre la actualización de su oferta.
    """
    status_text = "aceptada" if status == "accepted" else "rechazada"
    
    await manager.send_personal_message(
        {
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
        },
        buyer_id
    )

async def notify_other_buyers(
    product_id: str,
    buyer_ids: List[str],
    message: str,
):
    """
    Función para notificar a otros compradores cuando una oferta es aceptada.
    """
    for buyer_id in buyer_ids:
        await manager.send_personal_message(
            {
                "type": "product",
                "action": "sold",
                "data": {
                    "product_id": product_id,
                    "message": message,
                }
            },
            buyer_id
        )

@router.delete("/{offer_id}", status_code=status.HTTP_200_OK)
async def cancel_offer(
    *,
    db: Session = Depends(deps.get_db),
    offer_id: str,
    cancel_data: dict = Body(..., description="Datos para cancelar la oferta", 
                           example={"version": 1}),
    current_user: User = Depends(deps.get_current_user),
    background_tasks: BackgroundTasks,
):
    """
    Cancelar una oferta realizada (solo el comprador puede cancelar).
    Requiere un cuerpo JSON con:
    - version: número de versión actual de la oferta

    Ejemplo:
    ```
    {
        "version": 1
    }
    ```
    """
    # Extraer versión del cuerpo del request
    version = cancel_data.get("version")
    if not version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El campo 'version' es requerido",
        )
    
    # Obtener la oferta con bloqueo pesimista
    offer = db.query(Offer).filter(Offer.id == offer_id).with_for_update().first()
    if not offer:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Oferta no encontrada",
        )
    
    # Verificar versión para control de concurrencia optimista
    if offer.version != version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La oferta ha sido modificada. Recarga y vuelve a intentar.",
        )
    
    # Verificar que el usuario sea el comprador
    if offer.buyer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el comprador puede cancelar la oferta",
        )
    
    # Verificar que la oferta esté pendiente
    if offer.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede cancelar una oferta con estado '{offer.status}'",
        )
    
    try:
        # Obtener información del producto y vendedor antes de eliminar
        product_id = offer.product_id
        seller_id = offer.seller_id
        
        # Eliminar la oferta (alternativa: cambiar estado a "cancelled")
        db.delete(offer)
        db.commit()
        
        # Notificar al vendedor sobre la cancelación (en segundo plano)
        background_tasks.add_task(
            notify_offer_cancelled,
            offer_id,
            product_id,
            offer.buyer_id,
            current_user.full_name,
            seller_id,
        )
        
        return {"message": "Oferta cancelada correctamente"}
    
    except Exception as e:
        db.rollback()
        logger.error(f"Error al cancelar oferta: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error interno del servidor",
        )

async def notify_offer_cancelled(
    offer_id: str,
    product_id: str,
    buyer_id: str,
    buyer_name: str,
    seller_id: str,
):
    """
    Función para notificar al vendedor sobre la cancelación de una oferta.
    """
    await manager.send_personal_message(
        {
            "type": "offer",
            "action": "cancelled",
            "data": {
                "id": offer_id,
                "product_id": product_id,
                "buyer_id": buyer_id,
                "buyer_name": buyer_name,
                "message": "El comprador ha cancelado su oferta",
            }
        },
        seller_id
    )