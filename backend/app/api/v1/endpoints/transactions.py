from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Any, List, Optional
import uuid
from datetime import datetime

from app.api import deps
from app.schemas.transaction import TransactionCreate, TransactionResponse
from app.models.transaction import Transaction
from app.models.product import Product
from app.models.offer import Offer
from app.models.user import User
from app.tasks.notifications import send_notification

router = APIRouter()

@router.post("/", response_model=TransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    *,
    db: Session = Depends(deps.get_db),
    transaction_in: TransactionCreate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Crear una nueva transacción.
    """
    # Verificar que el producto existe
    product = db.query(Product).filter(Product.id == transaction_in.product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado",
        )
    
    # Verificar que el usuario es el comprador
    # En una transacción, el usuario actual debe ser el comprador
    
    # Si se proporciona una oferta, verificar que existe y está aceptada
    offer = None
    if transaction_in.offer_id:
        offer = db.query(Offer).filter(
            Offer.id == transaction_in.offer_id,
            Offer.product_id == transaction_in.product_id,
            Offer.buyer_id == current_user.id,
            Offer.status == "accepted"
        ).first()
        
        if not offer:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Oferta no encontrada o no aceptada",
            )
    
    # Verificar que el producto está disponible para compra
    if product.status != "active" and (not offer or product.status != "sold"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El producto no está disponible para compra",
        )
    
    # Crear la transacción
    db_transaction = Transaction(
        product_id=transaction_in.product_id,
        buyer_id=current_user.id,
        seller_id=product.seller_id,
        offer_id=transaction_in.offer_id,
        amount=transaction_in.amount if transaction_in.amount else (offer.amount if offer else product.price),
        currency=product.currency,
        payment_method=transaction_in.payment_method,
        status="pending",
    )
    
    db.add(db_transaction)
    
    # Marcar el producto como vendido si no lo estaba
    if product.status != "sold":
        product.status = "sold"
        db.add(product)
    
    db.commit()
    db.refresh(db_transaction)
    
    # Notificar al vendedor usando Celery
    notification_data = {
        "id": db_transaction.id,
        "product_id": db_transaction.product_id,
        "product_title": product.title,
        "buyer_id": db_transaction.buyer_id,
        "buyer_name": current_user.full_name,
        "amount": db_transaction.amount,
        "currency": db_transaction.currency,
        "status": db_transaction.status,
        "created_at": db_transaction.created_at.isoformat(),
    }
    
    send_notification.delay(
        db_transaction.seller_id, 
        "transaction", 
        "created", 
        notification_data
    )
    
    return db_transaction

@router.get("/", response_model=List[TransactionResponse])
def get_transactions(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
    role: str = Query(..., description="Rol: 'buyer' para compras, 'seller' para ventas"),
    status: Optional[str] = Query(None, description="Estado de la transacción"),
) -> Any:
    """
    Obtener lista de transacciones.
    """
    query = db.query(Transaction)
    
    # Filtrar por rol (comprador o vendedor)
    if role == "buyer":
        query = query.filter(Transaction.buyer_id == current_user.id)
    elif role == "seller":
        query = query.filter(Transaction.seller_id == current_user.id)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El parámetro 'role' debe ser 'buyer' o 'seller'",
        )
    
    # Filtrar por estado
    if status:
        query = query.filter(Transaction.status == status)
    
    # Ordenar por fecha (más recientes primero)
    query = query.order_by(Transaction.created_at.desc())
    
    transactions = query.all()
    
    return transactions

@router.get("/{transaction_id}", response_model=TransactionResponse)
def get_transaction(
    *,
    db: Session = Depends(deps.get_db),
    transaction_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Obtener una transacción por su ID.
    """
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transacción no encontrada",
        )
    
    # Verificar que el usuario sea el comprador o el vendedor
    if transaction.buyer_id != current_user.id and transaction.seller_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver esta transacción",
        )
    
    return transaction

@router.patch("/{transaction_id}/status", response_model=TransactionResponse)
async def update_transaction_status(
    *,
    db: Session = Depends(deps.get_db),
    transaction_id: str,
    status: str = Query(..., description="Nuevo estado de la transacción"),
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Actualizar el estado de una transacción.
    """
    # Verificar que el estado sea válido
    valid_states = ["pending", "processing", "completed", "cancelled", "refunded"]
    if status not in valid_states:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El estado debe ser uno de: {', '.join(valid_states)}",
        )
    
    # Obtener la transacción
    transaction = db.query(Transaction).filter(Transaction.id == transaction_id).first()
    if not transaction:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Transacción no encontrada",
        )
    
    # Verificar que el usuario sea el vendedor o el comprador
    # Solo el vendedor puede confirmar la transacción y solo el comprador puede cancelarla
    if status in ["completed", "processing"] and transaction.seller_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el vendedor puede actualizar a este estado",
        )
    
    if status in ["cancelled", "refunded"] and transaction.buyer_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el comprador puede actualizar a este estado",
        )
    
    # Actualizar el estado
    transaction.status = status
    transaction.updated_at = datetime.now()
    db.add(transaction)
    db.commit()
    db.refresh(transaction)
    
    # Notificar al otro usuario usando Celery
    recipient_id = transaction.buyer_id if current_user.id == transaction.seller_id else transaction.seller_id
    
    status_text = {
        "pending": "pendiente",
        "processing": "en proceso",
        "completed": "completada",
        "cancelled": "cancelada",
        "refunded": "reembolsada"
    }.get(status, status)
    
    notification_data = {
        "id": transaction.id,
        "product_id": transaction.product_id,
        "user_id": current_user.id,
        "user_name": current_user.full_name,
        "status": status,
        "updated_at": transaction.updated_at.isoformat(),
        "message": f"La transacción ha sido marcada como {status_text}"
    }
    
    send_notification.delay(
        recipient_id,
        "transaction",
        "updated",
        notification_data
    )
    
    return transaction