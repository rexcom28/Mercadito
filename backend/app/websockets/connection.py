import uuid
from fastapi import WebSocket, WebSocketDisconnect, HTTPException, status
import json
import logging
from typing import Dict, List, Any, Optional, Set
import asyncio
import redis.asyncio as redis
from app.core.config import settings
import time
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.connection_timestamps: Dict[str, float] = {}  # Para rastrear tiempo de conexión
        self.redis_pool = None
        self.ping_interval = 30  # Segundos entre pings
        self.ping_timeout = 10   # Segundos para esperar pong
        self.ongoing_pings: Dict[str, asyncio.Task] = {}
        self.failed_ping_users: Set[str] = set()  # Usuarios con pings fallidos
        self.reconnection_info: Dict[str, Dict[str, Any]] = {}  # Info de reconexión por usuario
        
        # Iniciar tarea de monitoreo
        asyncio.create_task(self._connection_monitor())
        # Iniciar tarea de limpieza de reconexiones
        asyncio.create_task(self._clean_reconnection_info())

    async def _listen_to_redis_channel(self, user_id: str, websocket: WebSocket):
        """Escucha el canal de Redis para mensajes de Celery"""
        try:
            r = await self.get_redis()
            pubsub = r.pubsub()
            
            # Suscribirse al canal específico para este usuario
            channel_name = f"user:{user_id}:notifications"
            await pubsub.subscribe(channel_name)
            
            # Iniciar tarea de escucha
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    try:
                        # Decodificar y enviar el mensaje
                        data = json.loads(message['data'])
                        await websocket.send_json(data)
                    except Exception as e:
                        logger.error(f"Error procesando mensaje de Redis: {e}")
                        
        except Exception as e:
            logger.error(f"Error en escucha de Redis: {e}")
        finally:
            # Asegurar que se cierre la suscripción
            try:
                await pubsub.unsubscribe(channel_name)
            except:
                pass       
    async def get_redis(self) -> redis.Redis:
        if self.redis_pool is None:
            self.redis_pool = redis.ConnectionPool.from_url(
                settings.REDIS_URL, decode_responses=True
            )
        return redis.Redis(connection_pool=self.redis_pool)
        
    async def connect(self, websocket: WebSocket, user_id: str):
        try:
            await websocket.accept()
            # Iniciar tarea de escucha de Redis para mensajes de Celery
            asyncio.create_task(self._listen_to_redis_channel(user_id, websocket))
            
            # Si hay una conexión existente, cerrarla para evitar duplicados
            if user_id in self.active_connections:
                try:
                    old_ws = self.active_connections[user_id]
                    await old_ws.close(code=1000, reason="new_connection")
                    logger.info(f"Cerrada conexión anterior para usuario {user_id}")
                except Exception as e:
                    logger.warning(f"Error al cerrar conexión anterior: {e}")
            
            # Registrar conexión
            self.active_connections[user_id] = websocket
            self.connection_timestamps[user_id] = time.time()
            
            # Establecer info de reconexión si es nueva
            if user_id not in self.reconnection_info:
                self.reconnection_info[user_id] = {
                    "attempts": 0,
                    "last_backoff": 1,
                    "last_connected": datetime.now(),
                }
            else:
                # Resetear datos de reconexión si se conecta exitosamente
                self.reconnection_info[user_id]["attempts"] = 0
                self.reconnection_info[user_id]["last_backoff"] = 1
                self.reconnection_info[user_id]["last_connected"] = datetime.now()
            
            # Remover de la lista de pings fallidos si estaba
            if user_id in self.failed_ping_users:
                self.failed_ping_users.remove(user_id)
            
            # Iniciar ping para esta conexión
            self._start_ping_task(user_id, websocket)
            
            logger.info(f"Usuario {user_id} conectado. Total conexiones: {len(self.active_connections)}")
            
            # Enviar mensaje inmediato de confirmación con info de sesión
            try:
                session_info = {
                    "type": "connection_status",
                    "data": {
                        "status": "connected",
                        "session_id": str(uuid.uuid4()),  # ID de sesión único
                        "server_time": datetime.now(timezone.utc).isoformat(),
                        "ping_interval": self.ping_interval
                    }
                }
                await websocket.send_json(session_info)
            except Exception as e:
                logger.warning(f"Error al enviar confirmación inicial: {e}")
            
            # Publicar estado de conexión en Redis
            r = await self.get_redis()
            await r.publish(
                "user_presence", 
                json.dumps({
                    "user_id": user_id, 
                    "status": "online", 
                    "timestamp": time.time()
                })
            )
            await r.set(f"user:{user_id}:status", "online", ex=3600)  # TTL 1 hora
            
            # Guardar última sesión activa para reconexión
            await r.set(f"user:{user_id}:last_session", datetime.now().isoformat(), ex=86400)  # 24 horas
            
            return True
        except Exception as e:
            logger.error(f"Error en conexión WebSocket para usuario {user_id}: {str(e)}")
            await self._handle_reconnection(user_id)
            return False
        
    def _start_ping_task(self, user_id: str, websocket: WebSocket):
        """Inicia el ping periódico para mantener viva la conexión"""
        if user_id in self.ongoing_pings:
            self.ongoing_pings[user_id].cancel()
        
        self.ongoing_pings[user_id] = asyncio.create_task(
            self._ping_client(user_id, websocket)
        )
    
    async def _ping_client(self, user_id: str, websocket: WebSocket):
        """Envía pings periódicos al cliente y verifica respuesta"""
        try:
            while user_id in self.active_connections:
                await asyncio.sleep(self.ping_interval)
                
                try:
                    ping_start = time.time()
                    await websocket.send_json({"type": "ping", "timestamp": ping_start})
                    
                    # Esperar timeout para pong
                    pong_received = False
                    pong_timeout = asyncio.create_task(asyncio.sleep(self.ping_timeout))
                    
                    try:
                        # Este código simula esperar el pong, en la implementación real
                        # debería ser integrado con el loop de recepción de mensajes
                        await pong_timeout
                        
                        if not pong_received:
                            logger.warning(f"No se recibió pong del usuario {user_id}")
                            self.failed_ping_users.add(user_id)
                            
                            if self.failed_ping_users.count(user_id) >= 3:
                                logger.warning(f"3 pings fallidos consecutivos para {user_id}, cerrando conexión")
                                await self.force_disconnect(user_id, "ping_timeout")
                    
                    except asyncio.CancelledError:
                        # Se recibió pong (simulado)
                        pass
                
                except Exception as e:
                    logger.error(f"Error enviando ping a {user_id}: {str(e)}")
                    await self.force_disconnect(user_id, "ping_error")
        
        except asyncio.CancelledError:
            # La tarea fue cancelada, probablemente por desconexión
            pass
        except Exception as e:
            logger.error(f"Error en tarea de ping para {user_id}: {str(e)}")

    async def _connection_monitor(self):
        """Monitorea conexiones para detectar desconexiones silenciosas"""
        while True:
            try:
                await asyncio.sleep(60)  # Verificar cada minuto
                
                current_time = time.time()
                stale_connections = []
                
                for user_id, timestamp in self.connection_timestamps.items():
                    # Si no hay ping por más de 2 minutos, la conexión probablemente está muerta
                    if current_time - timestamp > 120:
                        stale_connections.append(user_id)
                
                for user_id in stale_connections:
                    logger.warning(f"Conexión obsoleta detectada para {user_id}")
                    await self.force_disconnect(user_id, "stale_connection")
            
            except Exception as e:
                logger.error(f"Error en monitor de conexiones: {str(e)}")
    
    async def _clean_reconnection_info(self):
        """Limpia información de reconexión antigua"""
        while True:
            try:
                await asyncio.sleep(3600)  # Cada hora
                
                current_time = datetime.now()
                expired_users = []
                
                for user_id, info in self.reconnection_info.items():
                    # Mantener datos de reconexión solo por 24 horas
                    if (current_time - info["last_connected"]) > timedelta(hours=24):
                        expired_users.append(user_id)
                
                for user_id in expired_users:
                    del self.reconnection_info[user_id]
                
                logger.info(f"Limpieza de reconexión: eliminados {len(expired_users)} usuarios obsoletos")
            
            except Exception as e:
                logger.error(f"Error en limpieza de info de reconexión: {str(e)}")
    
    async def _handle_reconnection(self, user_id: str):
        """Gestiona la reconexión con backoff exponencial"""
        if user_id not in self.reconnection_info:
            self.reconnection_info[user_id] = {
                "attempts": 0,
                "last_backoff": 1,
                "last_connected": datetime.now(),
            }
        
        info = self.reconnection_info[user_id]
        info["attempts"] += 1
        
        # Calcular backoff exponencial con jitter (aleatorio)
        # Formula: min(max_backoff, base * 2^attempts + random_jitter)
        base_backoff = 1
        # Reducir max_backoff para clientes móviles
        max_backoff = 60  # 1 minuto máximo para entornos móviles (era 300 - 5 minutos)
        
        # Calcular backoff exponencial con menos agresividad
        power = min(info["attempts"], 6)  # Limitar exponente para evitar esperas muy largas
        backoff = min(
            max_backoff,
            base_backoff * (2 ** power) + (time.time() % 1)  # jitter
        )
        
        info["last_backoff"] = backoff
        
        # Almacenar en Redis para posible uso en frontend
        try:
            r = await self.get_redis()
            reconnect_data = {
                "attempts": info["attempts"],
                "backoff": backoff,
                "next_attempt": (datetime.now() + timedelta(seconds=backoff)).isoformat(),
                "retry_delay": backoff  # Explícitamente incluir retry_delay para clientes
            }
            
            await r.set(
                f"user:{user_id}:reconnect", 
                json.dumps(reconnect_data),
                ex=int(backoff * 2)  # TTL
            )
            
            # También enviar el mensaje de reconnect a otros dispositivos del mismo usuario
            # que puedan estar conectados
            try:
                if user_id in self.active_connections:
                    websocket = self.active_connections[user_id]
                    await websocket.send_json({
                        "type": "reconnect_info",
                        "data": reconnect_data
                    })
            except Exception as e:
                # No es crítico si falla
                logger.warning(f"No se pudo enviar info de reconexión: {e}")
                
        except Exception as e:
            logger.error(f"Error al guardar info de reconexión en Redis: {str(e)}")
        
        logger.info(f"Reconexión para usuario {user_id}: intento {info['attempts']}, backoff {backoff}s")

    async def force_disconnect(self, user_id: str, reason: str = "unknown"):
        """Fuerza desconexión y maneja estado de usuario"""
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            try:
                # Notificar al cliente antes de desconectar
                await websocket.send_json({
                    "type": "system",
                    "action": "disconnect",
                    "data": {"reason": reason}
                })
                await websocket.close(code=1000, reason=reason)
            except Exception:
                # No importa si falla al enviar el mensaje de cierre
                pass
            
            # Proceder con la desconexión
            self.disconnect(user_id, reason)
    
    def disconnect(self, user_id: str, reason: str = "unknown"):
        """Maneja la lógica de desconexión"""
        if user_id in self.active_connections:
            del self.active_connections[user_id]
            
            if user_id in self.connection_timestamps:
                del self.connection_timestamps[user_id]
            
            if user_id in self.ongoing_pings:
                self.ongoing_pings[user_id].cancel()
                del self.ongoing_pings[user_id]
            
            logger.info(f"Usuario {user_id} desconectado ({reason}). Total conexiones: {len(self.active_connections)}")
            
            # Ejecutar en una tarea asíncrona separada para evitar bloqueos
            asyncio.create_task(self._publish_disconnect(user_id, reason))
    
    async def _publish_disconnect(self, user_id: str, reason: str):
        try:
            r = await self.get_redis()
            await r.publish(
                "user_presence", 
                json.dumps({
                    "user_id": user_id, 
                    "status": "offline", 
                    "reason": reason,
                    "timestamp": time.time()
                })
            )
            await r.set(f"user:{user_id}:status", "offline", ex=3600)
            await r.set(f"user:{user_id}:last_disconnect", 
                        json.dumps({"timestamp": time.time(), "reason": reason}), 
                        ex=86400)  # 24 horas
        except Exception as e:
            logger.error(f"Error al publicar desconexión: {e}")
    
    async def send_personal_message(self, message: Any, user_id: str):
        if user_id in self.active_connections:
            websocket = self.active_connections[user_id]
            try:
                await websocket.send_json(message)
                logger.debug(f"Mensaje enviado a usuario {user_id}")
                
                # Actualizar timestamp de actividad
                self.connection_timestamps[user_id] = time.time()
                return True
            except WebSocketDisconnect:
                logger.warning(f"WebSocketDisconnect detectado al enviar mensaje a {user_id}")
                self.disconnect(user_id, "exception_on_send")
                await self._save_pending_message(user_id, message)
                return False
            except Exception as e:
                logger.error(f"Error al enviar mensaje a usuario {user_id}: {str(e)}")
                self.disconnect(user_id, "exception_on_send")
                await self._save_pending_message(user_id, message)
                return False
        else:
            # El usuario no está conectado, guardar en Redis para envío posterior
            await self._save_pending_message(user_id, message)
            return False
    
    async def _save_pending_message(self, user_id: str, message: Any):
        """Guarda mensaje pendiente para entrega posterior"""
        try:
            r = await self.get_redis()
            message_data = message if isinstance(message, str) else json.dumps(message)
            
            # Usar lista ordenada para mensajes pendientes
            await r.lpush(
                f"user:{user_id}:pending_messages",
                message_data
            )
            
            # Establecer TTL si no existe
            await r.expire(f"user:{user_id}:pending_messages", 86400 * 7)  # TTL 7 días
            
            # Incrementar contador de mensajes pendientes
            await r.incr(f"user:{user_id}:pending_count")
            await r.expire(f"user:{user_id}:pending_count", 86400 * 7)
            
            logger.info(f"Mensaje guardado para entrega posterior a {user_id}")
            return True
        except Exception as e:
            logger.error(f"Error al guardar mensaje pendiente: {e}")
            return False
    
    async def broadcast(self, message: Any, exclude_user: Optional[str] = None):
        """Envía un mensaje a todos los usuarios conectados"""
        disconnected_users = []
        
        for user_id, websocket in self.active_connections.items():
            if exclude_user and user_id == exclude_user:
                continue
                
            try:
                await websocket.send_json(message)
                # Actualizar timestamp de actividad
                self.connection_timestamps[user_id] = time.time()
            except WebSocketDisconnect:
                disconnected_users.append(user_id)
            except Exception as e:
                logger.error(f"Error al enviar broadcast a {user_id}: {e}")
                disconnected_users.append(user_id)
        
        # Limpiar conexiones cerradas
        for user_id in disconnected_users:
            self.disconnect(user_id, "exception_on_broadcast")
    
    async def broadcast_to_channel(self, channel: str, message: Any):
        """Envía un mensaje a través de Redis pub/sub para mayor escalabilidad"""
        try:
            r = await self.get_redis()
            message_data = message if isinstance(message, str) else json.dumps(message)
            await r.publish(
                channel,
                message_data
            )
            logger.debug(f"Mensaje publicado en canal {channel}")
            return True
        except Exception as e:
            logger.error(f"Error al publicar en canal {channel}: {e}")
            return False
    
    async def get_pending_messages(self, user_id: str) -> List[dict]:
        """Recupera mensajes pendientes para un usuario"""
        try:
            r = await self.get_redis()
            # Obtener todos los mensajes y luego eliminarlos
            messages = []
            while True:
                message = await r.rpop(f"user:{user_id}:pending_messages")
                if not message:
                    break
                
                try:
                    # Intentar parsear como JSON
                    messages.append(json.loads(message))
                except json.JSONDecodeError:
                    # Si no es JSON, añadir como string
                    messages.append(message)
            
            # Restablecer contador a cero
            if messages:
                await r.set(f"user:{user_id}:pending_count", 0, ex=86400 * 7)
            
            return messages
        except Exception as e:
            logger.error(f"Error al recuperar mensajes pendientes: {e}")
            return []
    
    async def get_user_status(self, user_id: str) -> dict:
        """Obtiene el estado de conexión de un usuario"""
        try:
            r = await self.get_redis()
            status = await r.get(f"user:{user_id}:status") or "unknown"
            pending_count = int(await r.get(f"user:{user_id}:pending_count") or 0)
            
            last_seen = None
            last_disconnect_data = await r.get(f"user:{user_id}:last_disconnect")
            if last_disconnect_data:
                try:
                    last_disconnect = json.loads(last_disconnect_data)
                    last_seen = last_disconnect.get("timestamp")
                except:
                    pass
            
            return {
                "status": status,
                "is_online": status == "online",
                "pending_messages": pending_count,
                "last_seen": last_seen
            }
        except Exception as e:
            logger.error(f"Error al obtener estado de usuario: {e}")
            return {
                "status": "unknown",
                "is_online": False,
                "pending_messages": 0,
                "last_seen": None
            }

# Singleton global para usar en toda la aplicación
manager = ConnectionManager()