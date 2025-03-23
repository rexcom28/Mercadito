from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, HTTPException, status
from app.core.security import decode_jwt_token
from app.websockets.connection import manager
import json
import logging
from typing import Dict, Any, Optional
import asyncio

logger = logging.getLogger(__name__)

websocket_router = APIRouter()

async def get_user_from_token(token: str) -> Dict[str, Any]:
    """Verifica y decodifica el token JWT para WebSockets"""
    payload = decode_jwt_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar las credenciales",
        )
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado",
        )
    return {"user_id": user_id}

@websocket_router.websocket("/ws/{token}")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """Endpoint principal de WebSocket para la comunicación en tiempo real"""
    try:
        # Verificar token y obtener user_id
        user_data = await get_user_from_token(token)
        user_id = user_data["user_id"]
        
        # Aceptar conexión
        await manager.connect(websocket, user_id)
        
        # Enviar mensajes pendientes al usuario que acaba de conectarse
        pending_messages = await manager.get_pending_messages(user_id)
        for message in pending_messages:
            await websocket.send_json(message)
            
        # Enviar notificación de estado
        await websocket.send_json({
            "type": "system",
            "action": "connected",
            "data": {"message": "Conectado al servidor"}
        })
        
        # Iniciar tarea de heartbeat
        heartbeat_task = asyncio.create_task(send_heartbeat(websocket))
        
        try:
            # Loop principal para recibir mensajes
            while True:
                data = await websocket.receive_text()
                await process_message(data, user_id)
        except WebSocketDisconnect:
            manager.disconnect(user_id)
            heartbeat_task.cancel()
        except Exception as e:
            logger.error(f"Error en websocket de usuario {user_id}: {e}")
            manager.disconnect(user_id)
            heartbeat_task.cancel()
            
    except HTTPException as e:
        # Error de autenticación
        await websocket.accept()
        await websocket.send_json({
            "type": "error",
            "data": {"message": e.detail}
        })
        await websocket.close(code=1008)  # Código de error de política
    except Exception as e:
        logger.error(f"Error inesperado en websocket: {e}")
        try:
            await websocket.accept()
            await websocket.send_json({
                "type": "error",
                "data": {"message": "Error interno del servidor"}
            })
            await websocket.close(code=1011)  # Error interno
        except:
            pass

async def send_heartbeat(websocket: WebSocket):
    """Envía un heartbeat periódico para mantener la conexión activa"""
    try:
        while True:
            await asyncio.sleep(30)  # Cada 30 segundos
            await websocket.send_json({"type": "heartbeat"})
    except:
        # La conexión se cerró, no necesitamos hacer nada aquí
        pass

async def process_message(data: str, user_id: str):
    """Procesa los mensajes recibidos del cliente"""
    try:
        message = json.loads(data)
        message_type = message.get("type")
        
        if message_type == "chat_message":
            # Mensaje de chat
            recipient_id = message.get("recipient_id")
            if recipient_id:
                # Añadir remitente al mensaje
                message["sender_id"] = user_id
                await manager.send_personal_message(message, recipient_id)
                
        elif message_type == "product_update":
            # Actualizaciones de productos (transmitido a todos)
            await manager.broadcast_to_channel("product_updates", message)
            
        elif message_type == "offer":
            # Oferta para un producto
            seller_id = message.get("seller_id")
            if seller_id:
                message["buyer_id"] = user_id
                await manager.send_personal_message(message, seller_id)
                
        elif message_type == "heartbeat_response":
            # Respuesta al heartbeat, no se necesita hacer nada
            pass
            
    except json.JSONDecodeError:
        logger.error(f"Mensaje recibido no es JSON válido: {data}")
    except Exception as e:
        logger.error(f"Error al procesar mensaje: {e}")