from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from typing import Any, List, Optional
from datetime import datetime
import uuid

from app.api import deps
from app.schemas.product import ProductCreate, ProductResponse, ProductUpdate, ProductImageCreate
from app.models.product import Product
from app.models.product_image import ProductImage
from app.models.user import User
from app.websockets.connection import manager

router = APIRouter()

@router.post("/", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    *,
    db: Session = Depends(deps.get_db),
    product_in: ProductCreate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Crear un nuevo producto.
    """
    # Verificar que el usuario sea vendedor
    if not current_user.is_seller:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El usuario no tiene permisos de vendedor",
        )
    
    # Crear el producto
    db_product = Product(
        **product_in.dict(exclude={"images"}),
        seller_id=current_user.id,
    )
    
    db.add(db_product)
    db.commit()
    db.refresh(db_product)
    
    # Crear imágenes del producto si existen
    if product_in.images:
        for i, image_url in enumerate(product_in.images):
            is_primary = i == 0  # La primera imagen es la principal
            db_image = ProductImage(
                product_id=db_product.id,
                image_url=image_url,
                is_primary=is_primary,
                order=i,
            )
            db.add(db_image)
        
        db.commit()
        db.refresh(db_product)
    
    # Notificar a través de WebSockets sobre el nuevo producto
    await manager.broadcast_to_channel(
        "product_updates",
        {
            "type": "product_update",
            "action": "created",
            "data": {
                "id": db_product.id,
                "title": db_product.title,
                "price": db_product.price,
                "seller_id": db_product.seller_id,
                "seller_name": current_user.full_name,
                "created_at": db_product.created_at.isoformat(),
            }
        }
    )
    
    return db_product

@router.get("/", response_model=List[ProductResponse])
def get_products(
    *,
    db: Session = Depends(deps.get_db),
    skip: int = 0,
    limit: int = 100,
    status: Optional[str] = Query(None, description="Estado del producto (active, sold, unavailable)"),
    min_price: Optional[float] = Query(None, description="Precio mínimo"),
    max_price: Optional[float] = Query(None, description="Precio máximo"),
    seller_id: Optional[str] = Query(None, description="ID del vendedor"),
) -> Any:
    """
    Obtener lista de productos con filtros opcionales.
    """
    query = db.query(Product)
    
    # Aplicar filtros
    if status:
        query = query.filter(Product.status == status)
    else:
        # Por defecto, solo mostrar productos activos
        query = query.filter(Product.status == "active")
    
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    
    if seller_id:
        query = query.filter(Product.seller_id == seller_id)
    
    # Ordenar por fecha de creación (más recientes primero)
    query = query.order_by(Product.created_at.desc())
    
    # Paginación
    products = query.offset(skip).limit(limit).all()
    
    return products

@router.get("/{product_id}", response_model=ProductResponse)
def get_product(
    *,
    db: Session = Depends(deps.get_db),
    product_id: str,
) -> Any:
    """
    Obtener un producto por su ID.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado",
        )
    
    return product

@router.patch("/{product_id}", response_model=ProductResponse)
async def update_product(
    *,
    db: Session = Depends(deps.get_db),
    product_id: str,
    product_in: ProductUpdate,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Actualizar un producto.
    """
    # Obtener el producto
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado",
        )
    
    # Verificar propiedad del producto
    if product.seller_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para modificar este producto",
        )
    
    # Actualizar solo los campos proporcionados
    update_data = product_in.dict(exclude_unset=True)
    for key, value in update_data.items():
        if key != "images":  # Las imágenes se manejan por separado
            setattr(product, key, value)
    
    # Actualizar imágenes si se proporcionan
    if "images" in update_data:
        # Eliminar imágenes existentes
        db.query(ProductImage).filter(ProductImage.product_id == product_id).delete()
        
        # Crear nuevas imágenes
        for i, image_url in enumerate(product_in.images):
            is_primary = i == 0  # La primera imagen es la principal
            db_image = ProductImage(
                product_id=product.id,
                image_url=image_url,
                is_primary=is_primary,
                order=i,
            )
            db.add(db_image)
    
    product.updated_at = datetime.now()
    db.add(product)
    db.commit()
    db.refresh(product)
    
    # Notificar a través de WebSockets sobre la actualización
    await manager.broadcast_to_channel(
        "product_updates",
        {
            "type": "product_update",
            "action": "updated",
            "data": {
                "id": product.id,
                "title": product.title,
                "price": product.price,
                "status": product.status,
                "updated_at": product.updated_at.isoformat(),
            }
        }
    )
    
    return product

@router.delete("/{product_id}", status_code=status.HTTP_200_OK)
async def delete_product(
    *,
    db: Session = Depends(deps.get_db),
    product_id: str,
    current_user: User = Depends(deps.get_current_user),
) -> Any:
    """
    Eliminar un producto.
    """
    # Obtener el producto
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Producto no encontrado",
        )
    
    # Verificar propiedad del producto
    if product.seller_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para eliminar este producto",
        )
    
    # Actualizar el estado a "unavailable" en lugar de eliminar
    product.status = "unavailable"
    db.add(product)
    db.commit()
    
    # Notificar a través de WebSockets sobre la eliminación
    await manager.broadcast_to_channel(
        "product_updates",
        {
            "type": "product_update",
            "action": "deleted",
            "data": {
                "id": product.id,
            }
        }
    )
    
    return {"message": "Producto eliminado correctamente"}