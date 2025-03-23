from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import Any, List
import uuid
from fastapi.security import OAuth2PasswordRequestForm
from app.api import deps
from app.core.security import get_password_hash, verify_password, create_access_token
from app.schemas.user import UserCreate, UserResponse, UserLogin, Token
from app.models.user import User

router = APIRouter()

@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    *,
    db: Session = Depends(deps.get_db),
    user_in: UserCreate,
) -> Any:
    """
    Crear un nuevo usuario.
    """
    # Verificar si el email ya existe
    user = db.query(User).filter(User.email == user_in.email).first()
    if user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El correo electrónico ya está registrado",
        )
    
    # Crear nuevo usuario
    user_data = user_in.dict(exclude={"password"})
    user_data["hashed_password"] = get_password_hash(user_in.password)
    db_user = User(**user_data)
    
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    
    return db_user

@router.post("/login", response_model=Token)
def login(
    db: Session = Depends(deps.get_db),
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> Any:
    """
    Obtener token de acceso para futuras peticiones.
    """
    # Buscar usuario por email (ahora usando username del formulario)
    user = db.query(User).filter(User.email == form_data.username).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
        )
    
    # Verificar contraseña (ahora usando password del formulario)
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email o contraseña incorrectos",
        )
    
    # Verificar que el usuario esté activo
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo",
        )
    
    # Crear token de acceso
    access_token = create_access_token(
        data={"sub": user.id}
    )
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user.id,
        "is_seller": user.is_seller,
    }

@router.get("/me", response_model=UserResponse)
def get_current_user(
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Obtener información del usuario autenticado.
    """
    return current_user

@router.patch("/me", response_model=UserResponse)
def update_current_user(
    *,
    db: Session = Depends(deps.get_db),
    current_user: User = Depends(deps.get_current_user),
    full_name: str = None,
    phone: str = None,
    profile_image: str = None,
    is_seller: bool = None,
) -> Any:
    """
    Actualizar información del usuario actual.
    """
    # Actualizar solo los campos proporcionados
    update_data = {}
    if full_name is not None:
        update_data["full_name"] = full_name
    if phone is not None:
        update_data["phone"] = phone
    if profile_image is not None:
        update_data["profile_image"] = profile_image
    if is_seller is not None:
        update_data["is_seller"] = is_seller
    
    # Si no hay datos para actualizar, devolver usuario actual
    if not update_data:
        return current_user
    
    # Actualizar usuario
    for key, value in update_data.items():
        setattr(current_user, key, value)
    
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    
    return current_user

@router.get("/{user_id}", response_model=UserResponse)
def get_user_by_id(
    user_id: str,
    db: Session = Depends(deps.get_db),
) -> Any:
    """
    Obtener información pública de un usuario por su ID.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )
    
    # Solo devolver si está activo
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )
    
    return user