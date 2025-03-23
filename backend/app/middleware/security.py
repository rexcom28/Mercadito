from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_429_TOO_MANY_REQUESTS, HTTP_403_FORBIDDEN
import time
import redis.asyncio as redis
import logging
import json
from typing import Dict, List, Optional, Tuple, Callable, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

class RateLimitExceeded(Exception):
    """Excepción cuando se excede el límite de tasa"""
    pass

class SecurityMiddleware(BaseHTTPMiddleware):
    """
    Middleware para mejorar la seguridad de la aplicación:
    - Añade encabezados de seguridad
    - Implementa limitación de tasa (rate limiting)
    - Detecta y bloquea peticiones potencialmente maliciosas
    """
    
    def __init__(
        self, 
        app: FastAPI, 
        redis_url: Optional[str] = None,
        exclude_paths: Optional[List[str]] = None,
    ):
        super().__init__(app)
        self.redis_url = redis_url or settings.REDIS_URL
        self.exclude_paths = exclude_paths or ["/docs", "/redoc", "/openapi.json"]
        self.redis_pool = None
        self.enabled = settings.RATE_LIMIT_ENABLED
        
        # Configuración de rate limiting
        self.default_limit = settings.RATE_LIMIT_DEFAULT_LIMIT
        self.default_period = settings.RATE_LIMIT_DEFAULT_PERIOD
        self.rate_limit_by_ip = settings.RATE_LIMIT_BY_IP
        
        # Rutas con límites específicos
        self.path_limits: Dict[str, Tuple[int, int]] = {
            "/api/v1/users/login": (20, 3600),        # 20 intentos por hora
            "/api/v1/users/register": (10, 3600),     # 10 registros por hora
            "/api/v1/products": (100, 3600),          # 100 creaciones/actualizaciones por hora
            "/ws": (1000, 3600),                      # 1000 conexiones por hora
        }
        
        # Configuración de bloqueos
        self.block_after_violations = 5               # Número de veces que se debe exceder el límite antes de bloquear
        self.block_duration = 86400                   # Duración del bloqueo (24 horas)
        
        # Lista de IPs bloqueadas en memoria
        self.blocked_ips: Dict[str, float] = {}
        
        # Lista de patrones maliciosos
        self.malicious_patterns = [
            "../../",                                 # Directory traversal
            "../etc/passwd",                          # Path traversal
            "SELECT.*FROM",                           # SQL injection
            "UNION.*SELECT",                          # SQL injection
            "eval\\(",                                # Code injection
            "<script",                                # XSS
            "javascript:",                            # XSS
            "onload=",                                # XSS
            "alert\\(",                               # XSS testing
        ]
    
    async def get_redis(self) -> redis.Redis:
        """Obtiene una conexión a Redis para rate limiting"""
        if self.redis_pool is None:
            self.redis_pool = redis.ConnectionPool.from_url(
                self.redis_url, decode_responses=True
            )
        return redis.Redis(connection_pool=self.redis_pool)
    
    async def is_path_excluded(self, path: str) -> bool:
        """Verifica si la ruta está excluida de rate limiting"""
        return any(path.startswith(excluded) for excluded in self.exclude_paths)
    
    async def get_client_identifier(self, request: Request) -> str:
        """
        Obtiene un identificador único para el cliente (IP + usuario si está autenticado)
        """
        client_ip = request.client.host if request.client else "unknown"
        
        # Si está configurado para limitar por IP
        if self.rate_limit_by_ip:
            return f"ip:{client_ip}"
        
        # Intentar obtener el usuario autenticado desde el token
        user_id = "anonymous"
        try:
            auth_header = request.headers.get("Authorization")
            if auth_header and auth_header.startswith("Bearer "):
                # En una implementación real, aquí se validaría el token
                # y se extraería el user_id
                pass
        except:
            pass
        
        # Combinar IP + usuario para rate limiting más preciso
        return f"ip:{client_ip}:user:{user_id}"
    
    async def is_blocked(self, client_id: str) -> bool:
        """Verifica si el cliente está bloqueado"""
        # Verificar bloqueo en memoria
        ip = client_id.split(":")[1]
        if ip in self.blocked_ips:
            block_time = self.blocked_ips[ip]
            # Si el bloqueo ha expirado, eliminar
            if time.time() > block_time:
                del self.blocked_ips[ip]
                return False
            return True
        
        # Verificar bloqueo en Redis
        try:
            r = await self.get_redis()
            is_blocked = await r.get(f"block:{client_id}")
            return bool(is_blocked)
        except:
            # Si hay error con Redis, confiar en memoria
            return False
    
    async def increment_violation(self, client_id: str) -> int:
        """
        Incrementa el contador de violaciones de rate limit y
        bloquea si es necesario
        """
        try:
            r = await self.get_redis()
            violations_key = f"violations:{client_id}"
            
            # Incrementar contador
            violations = await r.incr(violations_key)
            
            # Establecer TTL si es la primera violación
            if violations == 1:
                await r.expire(violations_key, 86400)  # 24 horas
            
            # Bloquear si excede el límite
            if violations >= self.block_after_violations:
                block_key = f"block:{client_id}"
                await r.set(block_key, "1", ex=self.block_duration)
                
                # Guardar también en memoria para acceso rápido
                ip = client_id.split(":")[1]
                self.blocked_ips[ip] = time.time() + self.block_duration
                
                logger.warning(f"Cliente bloqueado por exceso de violaciones: {client_id}")
            
            return violations
        except Exception as e:
            logger.error(f"Error al incrementar violaciones: {str(e)}")
            return 0
    
    async def is_rate_limited(
        self, 
        client_id: str, 
        path: str
    ) -> Tuple[bool, int, int, int]:
        """
        Verifica si el cliente ha excedido su límite de tasa.
        Retorna: (limitado, actual, límite, reset)
        """
        # Si no está habilitado rate limiting
        if not self.enabled:
            return False, 0, 0, 0
        
        # Determinar límite y periodo para la ruta
        path_key = next((p for p in self.path_limits.keys() if path.startswith(p)), None)
        
        if path_key:
            limit, period = self.path_limits[path_key]
        else:
            limit, period = self.default_limit, self.default_period
        
        try:
            r = await self.get_redis()
            redis_key = f"ratelimit:{client_id}:{path}"
            
            # Obtener contador actual
            count = await r.get(redis_key)
            count = int(count) if count else 0
            
            # Obtener TTL
            ttl = await r.ttl(redis_key)
            reset_time = int(time.time() + (ttl if ttl > 0 else period))
            
            # Verificar si excede el límite
            if count >= limit:
                return True, count, limit, reset_time
            
            # Incrementar contador
            pipe = r.pipeline()
            pipe.incr(redis_key)
            
            # Establecer TTL si es la primera petición
            if count == 0:
                pipe.expire(redis_key, period)
            
            await pipe.execute()
            
            return False, count + 1, limit, reset_time
        
        except Exception as e:
            logger.error(f"Error en rate limiting: {str(e)}")
            # Si hay error, permitir la petición
            return False, 0, limit, int(time.time() + period)
    
    async def detect_malicious_request(self, request: Request) -> bool:
        """Detecta patrones maliciosos en la petición"""
        try:
            # Verificar URI
            uri = request.url.path
            for pattern in self.malicious_patterns:
                if pattern in uri:
                    logger.warning(f"Patrón malicioso detectado en URI: {uri}")
                    return True
            
            # Verificar query params
            for key, value in request.query_params.items():
                for pattern in self.malicious_patterns:
                    if pattern in value:
                        logger.warning(f"Patrón malicioso detectado en query param: {key}={value}")
                        return True
            
            # Verificar headers
            for key, value in request.headers.items():
                for pattern in self.malicious_patterns:
                    if pattern in value:
                        logger.warning(f"Patrón malicioso detectado en header: {key}={value}")
                        return True
            
            # Para body, sería más complejo ya que necesitaríamos leer el stream
            # y luego reemplazarlo, lo cual tiene implicaciones de rendimiento
            
            return False
        
        except Exception as e:
            logger.error(f"Error al detectar patrones maliciosos: {str(e)}")
            return False
    
    async def add_security_headers(self, response: Response) -> None:
        """Añade cabeceras de seguridad a la respuesta"""
        # Determinar la URL del path para ajustar CSP según la ruta
        path = ""
        if hasattr(response, "scope") and "path" in response.scope:
            path = response.scope["path"]
        elif "scope" in response.__dict__ and "path" in response.scope:
            path = response.scope["path"]
        
        # No aplicar CSP a la documentación
        if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi.json") or path.startswith("/static/"):
            # Eliminar CSP para documentación si existe
            if "Content-Security-Policy" in response.headers:
                del response.headers["Content-Security-Policy"]
        else:
            # CSP estricto para el resto de la aplicación
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "img-src 'self' data:; "
                "font-src 'self'; "
                "connect-src 'self'"
            )
        
        # X-Content-Type-Options
        response.headers["X-Content-Type-Options"] = "nosniff"
        
        # X-Frame-Options
        response.headers["X-Frame-Options"] = "DENY"
        
        # X-XSS-Protection
        response.headers["X-XSS-Protection"] = "1; mode=block"
        
        # Strict-Transport-Security (HSTS)
        if settings.ENVIRONMENT == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        
        # Referrer-Policy
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        
        # Permissions-Policy
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
    
    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Any]
    ) -> Response:
        # Tiempo de inicio para medir duración
        start_time = time.time()
        
        # Obtener identificador de cliente
        client_id = await self.get_client_identifier(request)
        path = request.url.path
        
        # Verificar si está excluido
        is_excluded = await self.is_path_excluded(path)
        
        # Guardar el path para usar después en add_security_headers
        # Almacenamos el path en una variable local que persistirá durante esta solicitud
        current_path = path
        
        # Solo aplicar rate limiting y detección para rutas no excluidas
        if not is_excluded:
            # Verificar si está bloqueado
            if await self.is_blocked(client_id):
                return Response(
                    content=json.dumps({
                        "detail": "Tu acceso ha sido bloqueado temporalmente debido a actividad sospechosa"
                    }),
                    status_code=HTTP_403_FORBIDDEN,
                    media_type="application/json"
                )
            
            # Detectar peticiones maliciosas
            if await self.detect_malicious_request(request):
                # Registrar violación e incrementar contador
                await self.increment_violation(client_id)
                
                return Response(
                    content=json.dumps({
                        "detail": "Solicitud denegada por motivos de seguridad"
                    }),
                    status_code=HTTP_403_FORBIDDEN,
                    media_type="application/json"
                )
            
            # Verificar rate limiting
            limited, current, limit, reset = await self.is_rate_limited(client_id, path)
            if limited:
                # Incrementar contador de violaciones
                await self.increment_violation(client_id)
                
                # Respuesta con headers de rate limiting
                return Response(
                    content=json.dumps({
                        "detail": "Demasiadas solicitudes. Por favor, inténtalo de nuevo más tarde."
                    }),
                    status_code=HTTP_429_TOO_MANY_REQUESTS,
                    headers={
                        "X-RateLimit-Limit": str(limit),
                        "X-RateLimit-Remaining": "0",
                        "X-RateLimit-Reset": str(reset),
                        "Retry-After": str(reset - int(time.time()))
                    },
                    media_type="application/json"
                )
        
        # Procesar la petición
        try:
            response = await call_next(request)
        except Exception as e:
            logger.error(f"Error no manejado: {str(e)}")
            response = Response(
                content=json.dumps({
                    "detail": "Error interno del servidor"
                }),
                status_code=500,
                media_type="application/json"
            )
        
        # Para rutas de documentación, No aplicar CSP
        if path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi.json") or path.startswith("/static/"):
            # Otras cabeceras de seguridad
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "SAMEORIGIN"  # Cambiado de DENY a SAMEORIGIN para la documentación
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
            
            # Eliminar CSP si existe
            if "Content-Security-Policy" in response.headers:
                del response.headers["Content-Security-Policy"]
        else:
            # Aplicar todas las cabeceras de seguridad para otras rutas
            await self.add_security_headers(response)
        
        # Añadir headers de rate limiting si no está excluido
        if not is_excluded and self.enabled:
            response.headers["X-RateLimit-Limit"] = str(limit)
            response.headers["X-RateLimit-Remaining"] = str(max(0, limit - current))
            response.headers["X-RateLimit-Reset"] = str(reset)
        
        # Añadir tiempo de procesamiento para depuración
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        
        return response

def setup_security_middleware(app: FastAPI) -> None:
    """Configura los middlewares de seguridad para la aplicación"""
    # CORS
    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[
                "X-RateLimit-Limit", 
                "X-RateLimit-Remaining", 
                "X-RateLimit-Reset",
                "X-Process-Time"
            ],
        )
    
    # Sesión (si se necesita)
    app.add_middleware(
        SessionMiddleware, 
        secret_key=settings.SECRET_KEY,
        max_age=3600,  # 1 hora
    )
    
    # Middleware de seguridad personalizado
    app.add_middleware(
        SecurityMiddleware,
        redis_url=settings.REDIS_URL,
        exclude_paths=[
            "/docs", 
            "/redoc", 
            "/openapi.json",
            "/static/",
        ],
    )
    
    logger.info("Middlewares de seguridad configurados")