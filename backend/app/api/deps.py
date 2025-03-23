#backend/app/api/v1/deps.py
import asyncio
from typing import Generator, AsyncGenerator
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text  # Importar text
from app.db.session import get_async_db
from app.core.security import decode_jwt_token
from app.models.user import User
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# Token URL (requerido para OAuth2PasswordBearer)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/users/login")

def get_db() -> Generator[Session, None, None]:
    """
    Dependency para obtener una sesión de base de datos sincrónica.
    """
    # Importamos aquí para evitar problemas de importación circular
    from app.db.session import SessionLocal, init_db_connection, _is_initialized
    
    # Verificar inicialización
    if not _is_initialized:
        logger.warning("Conexión a base de datos no inicializada en get_db, inicializando...")
        
        # Usar la inicialización síncrona directa
        try:
            from sqlalchemy import create_engine, text
            from sqlalchemy.orm import sessionmaker
            from app.core.config import settings
            
            # Crear motor sincrónico
            sync_engine = create_engine(
                str(settings.DATABASE_URL),
                pool_size=5,
                max_overflow=10,
                pool_timeout=30,
                pool_recycle=3600,
                pool_pre_ping=True,
                echo=settings.DEBUG
            )
            
            # Session maker para sesiones síncronas
            session_maker = sessionmaker(
                autocommit=False,
                autoflush=False,
                bind=sync_engine
            )
            
            # Asignar a globales
            import app.db.session as db_session
            db_session.sync_engine = sync_engine
            db_session.SessionLocal = session_maker
            
            # Actualizar la variable de inicialización
            db_session._is_initialized = True
            
            logger.info("Conexión a base de datos inicializada de forma sincrónica")
        except Exception as e:
            logger.error(f"AAAAAAAAAAAError al inicializar conexión de forma sincrónica: {e}")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"AAAAAAAAAAAAANo se pudo conectar a la base de datos {e}"
            )
    
    # Nos aseguramos que SessionLocal no sea None
    from app.db.session import SessionLocal
    if SessionLocal is None:
        logger.error("SessionLocal es None a pesar de la inicialización")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Error de configuración de base de datos"
        )
    
    db = SessionLocal()
    try:
        # Probar la conexión con text()
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
        yield db
    except HTTPException as http_exc:
        # Propagar excepciones HTTP (como 401 Unauthorized) sin transformarlas
        db.rollback()
        db.close()
        raise http_exc
    except Exception as e:
        # Solo convertir a 503 errores genuinos de base de datos
        logger.error(f"Error en sesión de base de datos: {e}")
        db.rollback()
        db.close()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error de conexión a la base de datos{e}"
        )
    finally:
        db.close()
async def get_current_user(
    db: Session = Depends(get_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    """
    Dependency para obtener el usuario actual autenticado.
    """
    payload = decode_jwt_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar las credenciales",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar las credenciales",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo",
        )
    
    return user

async def get_current_seller(
    current_user: User = Depends(get_current_user),
) -> User:
    """
    Dependency para verificar que el usuario es un vendedor.
    """
    if not current_user.is_seller:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario no tiene permisos de vendedor",
        )
    
    return current_user

# Versiones asíncronas de las dependencias

async def get_current_user_async(
    db: AsyncSession = Depends(get_async_db),
    token: str = Depends(oauth2_scheme),
) -> User:
    """
    Versión asíncrona de get_current_user.
    """
    payload = decode_jwt_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar las credenciales",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No se pudo validar las credenciales",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    from sqlalchemy import select
    stmt = select(User).where(User.id == user_id)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no encontrado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo",
        )
    
    return user

async def get_current_seller_async(
    current_user: User = Depends(get_current_user_async),
) -> User:
    """
    Versión asíncrona de get_current_seller.
    """
    if not current_user.is_seller:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario no tiene permisos de vendedor",
        )
    
    return current_user