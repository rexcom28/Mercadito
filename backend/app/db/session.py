##backend/app/db/session.py
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.pool import QueuePool
from sqlalchemy import text  # Importar text
from app.core.config import settings
import logging
import asyncio

logger = logging.getLogger(__name__)

# Base declarativa para los modelos
Base = declarative_base()

# Convertir URL de PostgreSQL a AsyncPostgreSQL
def get_async_db_url(url):
    """Convierte una URL de PostgreSQL a su versión asíncrona."""
    url_str = str(url)
    if url_str.startswith("postgresql://"):
        return url_str.replace("postgresql://", "postgresql+asyncpg://")
    return url_str

# Inicialización de engine con None
engine = None
AsyncSessionLocal = None
sync_engine = None
SessionLocal = None

# Control de inicialización
_is_initialized = False
_initialization_lock = asyncio.Lock()

async def init_db_connection(max_retries=5, initial_delay=1):
    """Inicializa la conexión a la base de datos con reintentos."""
    global engine, AsyncSessionLocal, sync_engine, SessionLocal, _is_initialized
    
    # Si ya está inicializado, no hacer nada
    if _is_initialized:
        return True
    
    # Usar lock para evitar inicializaciones concurrentes
    async with _initialization_lock:
        # Verificar de nuevo dentro del lock
        if _is_initialized:
            return True
        
        retry_count = 0
        last_exception = None
        
        while retry_count < max_retries:
            try:
                # Crear motor asíncrono
                engine = create_async_engine(
                    get_async_db_url(settings.DATABASE_URL),
                    echo=settings.DEBUG,
                    pool_size=5,
                    max_overflow=10,
                    pool_timeout=30,
                    pool_recycle=3600,
                    pool_pre_ping=True,
                )
                
                # Probar la conexión - USAR TEXT()
                async with engine.begin() as conn:
                    await conn.execute(text("SELECT 1"))
                
                logger.info(f"Conexión a la base de datos establecida (intento {retry_count + 1})")
                
                # Session maker para sesiones asíncronas
                AsyncSessionLocal = sessionmaker(
                    engine,
                    class_=AsyncSession,
                    expire_on_commit=False,
                    autocommit=False,
                    autoflush=False,
                )
                
                # Para compatibilidad con código sincrónico existente
                from sqlalchemy import create_engine
                from sqlalchemy.orm import sessionmaker as sync_sessionmaker
                
                sync_engine = create_engine(
                    str(settings.DATABASE_URL),
                    pool_size=5,
                    max_overflow=10,
                    pool_timeout=30,
                    pool_recycle=3600,
                    pool_pre_ping=True,
                    echo=settings.DEBUG,
                )
                
                SessionLocal = sync_sessionmaker(
                    autocommit=False,
                    autoflush=False,
                    bind=sync_engine
                )
                
                # Probar que la sesión sincrónica funciona - USAR TEXT()
                test_session = SessionLocal()
                test_session.execute(text("SELECT 1"))
                test_session.close()
                
                # Marcar como inicializado
                _is_initialized = True
                
                return True
                
            except Exception as e:
                retry_count += 1
                last_exception = e
                wait_time = initial_delay * (2 ** (retry_count - 1))  # Exponential backoff
                
                logger.warning(f"Intento {retry_count}/{max_retries} fallido para conectar a la base de datos: {e}")
                logger.warning(f"Reintentando en {wait_time} segundos...")
                
                await asyncio.sleep(wait_time)
        
        logger.error(f"No se pudo conectar a la base de datos después de {max_retries} intentos: {last_exception}")
        return False

# Dependencia para obtener una sesión de base de datos asíncrona
async def get_async_db():
    """
    Dependency para obtener una sesión de base de datos asíncrona.
    """
    # Asegurar que la conexión está inicializada
    if not _is_initialized:
        success = await init_db_connection()
        if not success:
            raise Exception("No se pudo establecer conexión con la base de datos")
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
    """
    Dependency para obtener una sesión de base de datos asíncrona.
    """
    # Asegurar que la conexión está inicializada
    if not _is_initialized:
        success = await init_db_connection()
        if not success:
            raise Exception("No se pudo establecer conexión con la base de datos")
    
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()