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
    from app.db.session import SessionLocal
    
    db = SessionLocal()
    try:
        # Probar conexión explícitamente antes de usar
        db.execute(text("SELECT 1"))
        yield db
    except Exception as e:
        logger.error(f"Error en sesión de base de datos: {e}")
        db.rollback()
        # Proporcionar un mensaje de error más descriptivo para ayudar en la depuración
        error_message = f"Error de conexión a la base de datos: {str(e)}"
        if "Connection refused" in str(e):
            error_message = "No se pudo conectar a la base de datos. Verifique que el servicio esté activo."
        elif "timeout" in str(e).lower():
            error_message = "Tiempo de espera agotado al conectar con la base de datos."
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=error_message
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