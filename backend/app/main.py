from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.openapi.docs import get_swagger_ui_html
from sqlalchemy.ext.asyncio import AsyncSession
import logging
import asyncio
import os
from datetime import datetime
from contextlib import asynccontextmanager

from app.api.api import api_router
from app.core.config import settings

from app.middleware.security import setup_security_middleware
from app.websockets.router import websocket_router
from app.tasks.offers import start_offer_expiration_task, stop_offer_expiration_task

# Configurar logging
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Tareas en segundo plano
background_tasks = []

# Inicializar la base de datos primero
async def initialize_database():
    from app.db.session import init_db_connection, _is_initialized
    
    if not _is_initialized:
        logger.info("Inicializando conexión a la base de datos...")
        await init_db_connection(max_retries=5, initial_delay=2)
    else:
        logger.info("La base de datos ya está inicializada")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Asegurarse que la base de datos esté inicializada
    await initialize_database()
    
    # Connect to the database
    from app.db.session import engine, _is_initialized
    from app.db.base_class import Base
    from sqlalchemy import text
    
    if not _is_initialized or engine is None:
        logger.error("No se pudo inicializar la conexión a la base de datos antes del lifespan")
        yield
        return
    
    # Retry parameters
    max_retries = 5
    retry_delay = 2  # Initial delay in seconds
    retry_count = 0
    
    while retry_count < max_retries:
        try:
            logger.info(f"Iniciando la aplicación en entorno: {settings.ENVIRONMENT}")
            
            # First try to drop type if exists (to fix the conflict)
            async with engine.begin() as conn:
                try:
                    await conn.execute(text("DROP TYPE IF EXISTS users CASCADE"))
                    logger.info("Tipo 'users' eliminado (si existía)")
                except Exception as e:
                    logger.warning(f"No se pudo eliminar el tipo 'users': {e}")
                
                # Drop tables in reverse dependency order
                tables = ["transactions", "messages", "offers", "product_images", "products", "users"]
                for table in tables:
                    try:
                        await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                        logger.info(f"Tabla '{table}' eliminada (si existía)")
                    except Exception as e:
                        logger.warning(f"Error al eliminar tabla {table}: {e}")
            
            # Then create all tables
            async with engine.begin() as conn:
                await conn.run_sync(lambda sync_conn: Base.metadata.create_all(sync_conn))
                
            logger.info("Tablas de base de datos creadas/verificadas")
            
            # Iniciar tareas en segundo plano
            await start_offer_expiration_task()
            logger.info("Tareas en segundo plano iniciadas")
            
            break  # Exit the retry loop if successful
            
        except Exception as e:
            retry_count += 1
            wait_time = retry_delay * (2 ** (retry_count - 1))  # Exponential backoff
            
            if retry_count < max_retries:
                logger.warning(f"Error al inicializar la base de datos (intento {retry_count}/{max_retries}): {e}")
                logger.warning(f"Reintentando en {wait_time} segundos...")
                await asyncio.sleep(wait_time)
            else:
                logger.error(f"Error al inicializar la base de datos después de {max_retries} intentos: {e}")
    
    yield
    
    # Shutdown logic
    logger.info("Deteniendo la aplicación...")
    
    # Stop background tasks
    for task in background_tasks:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    
    # Stop specific tasks
    await stop_offer_expiration_task()
    
    # Close database connections
    if engine is not None:
        await engine.dispose()
    
    logger.info("Conexiones a base de datos cerradas")
    logger.info("Aplicación detenida correctamente")

# Crear la aplicación FastAPI
app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API para marketplace en tiempo real",
    version="0.1.0",
    openapi_url=f"{settings.API_V1_STR}/openapi.json" if not settings.ENVIRONMENT == "production" else None,
    docs_url=None,  # Desactivamos endpoint de docs por defecto
    redoc_url=None,  # Desactivamos endpoint de redoc por defecto
    lifespan=lifespan,
)

# Evento de inicio para asegurarse que la BD está inicializada
@app.on_event("startup")
async def startup_event():
    await initialize_database()

# Configurar middlewares de seguridad
setup_security_middleware(app)

# Montar rutas para archivos estáticos si existen
try:
    static_dir = "static"
    os.makedirs(static_dir, exist_ok=True)
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    logger.info(f"Directorio de archivos estáticos montado: {static_dir}")
except Exception as e:
    logger.warning(f"No se pudieron montar archivos estáticos: {e}")

# Incluir routers
app.include_router(api_router, prefix=settings.API_V1_STR)
app.include_router(websocket_router)

# Endpoint personalizado para documentación (con autenticación en producción)
@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    """
    Endpoint personalizado para la documentación Swagger usando CDN.
    """
    return get_swagger_ui_html(
        openapi_url=f"{settings.API_V1_STR}/openapi.json",  # Asegúrate de que esta ruta es correcta
        title=f"{settings.PROJECT_NAME} - API Documentation",
        swagger_js_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.12.0/swagger-ui-bundle.js",
        swagger_css_url="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5.12.0/swagger-ui.css",
        swagger_ui_parameters={"persistAuthorization": True}
    )

# El resto del archivo sigue igual...