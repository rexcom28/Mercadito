from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks, Query
from sqlalchemy.orm import Session
from typing import Any, List, Optional
import uuid

from app.api import deps
from app.schemas.message import MessageCreate, MessageResponse
from app.models.message import Message
from app.models.user import User
from app.websockets.connection import manager

router = APIRouter()

@router.post("/", response_model=MessageResponse, status_code=status.HTTP_201_CREATED)
async def create_message(
    *,
    db: Session = Depends(deps.get_db),
    message_in: MessageCreate,
    current_user: User = Depends(deps.get_current_user),
    background_tasks: BackgroundTasks,
) -> Any:
    """
    Enviar un mensaje a otro usuario.
    """
    # Verificar que el destinatario existe
    recipient = db.query(User).filter(User.id == message_in.recipient_id).first()
    if not recipient or not recipient.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Destinatario no encontrado",
        )
    
    # Verificar que no se envía mensaje a uno mismo
    if message_in.recipient_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No puedes enviarte mensajes a ti mismo",
        )
    
    # Crear el mensaje
    db_message = Message(
        sender_id=current_user.id,
        recipient_id=message_in.recipient_id,
        content=message_in.content,
        related_product_id=message_in.related_product_id,
    )
    
    db.add(db_message)
    db.commit()
    db.refresh(db_message)
    
    # Notificar al destinatario a través de WebSockets
    background_tasks.add_task(
        notify_new_message,
        db_message.id,
        current_user.id,
        current_user.full_name,
        message_in.recipient_id,
        db_message.content,
        db_message.related_product_id,
        db_message.created_at.isoformat(),
    )
    
    return db_message

async def notify_new_message(
    message_id: str,
    sender_id: str,
    sender_name: str,
    recipient_id: str,
    content: str,
    related_product_id: Optional[str],
    created_at: str,
):
    """
    Función de notificación para nuevos mensajes.
    """
    await manager.send_personal_message(
        {
            "type": "message",
            "action": "created",
            "data": {
                "id": message_id,
                "sender_id": sender_id,
                "sender_name": sender_name,
                "content": content,
                "related_product_id": related_product_id,
                "created_at": created_at,
                "is_read": False,
            }
        },
        recipient_id
    )

@router.get("/", response_model=List[MessageResponse])
def get_messages(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
    contact_id: Optional[str] = Query(None, description="ID del otro usuario para filtrar conversación"),
    product_id: Optional[str] = Query(None, description="ID del producto para filtrar mensajes"),
    unread_only: bool = Query(False, description="Filtrar solo mensajes no leídos"),
) -> Any:
    """
    Obtener mensajes del usuario actual.
    """
    
    query = db.query(Message).filter(
        (Message.recipient_id == current_user.id) | (Message.sender_id == current_user.id)
    )
    
    # Filtrar por contacto (conversación con otro usuario)
    if contact_id:
        query = query.filter(
            ((Message.recipient_id == contact_id) & (Message.sender_id == current_user.id)) |
            ((Message.recipient_id == current_user.id) & (Message.sender_id == contact_id))
        )
    
    # Filtrar por producto
    if product_id:
        query = query.filter(Message.related_product_id == product_id)
    
    # Filtrar solo mensajes no leídos
    if unread_only:
        query = query.filter(
            (Message.recipient_id == current_user.id) & (Message.is_read == False)
        )
    
    # Ordenar por fecha (más recientes primero)
    query = query.order_by(Message.created_at.desc())
    
    messages = query.all()
    
    return messages

@router.get("/{message_id}", response_model=MessageResponse)
def get_message(
    *,
    db: Session = Depends(deps.get_db),
    message_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Obtener un mensaje por su ID.
    """
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mensaje no encontrado",
        )
    
    # Verificar que el usuario sea el remitente o el destinatario
    if message.sender_id != current_user.id and message.recipient_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver este mensaje",
        )
    
    # Marcar como leído si el usuario es el destinatario
    if message.recipient_id == current_user.id and not message.is_read:
        message.is_read = True
        db.add(message)
        db.commit()
        db.refresh(message)
    
    return message

@router.patch("/{message_id}/read", response_model=MessageResponse)
def mark_message_as_read(
    *,
    db: Session = Depends(deps.get_db),
    message_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Marcar un mensaje como leído.
    """
    message = db.query(Message).filter(Message.id == message_id).first()
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mensaje no encontrado",
        )
    
    # Verificar que el usuario sea el destinatario
    if message.recipient_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el destinatario puede marcar el mensaje como leído",
        )
    
    # Marcar como leído
    message.is_read = True
    db.add(message)
    db.commit()
    db.refresh(message)
    
    return message