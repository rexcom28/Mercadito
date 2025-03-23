from pydantic import BaseModel, validator, Field
from typing import Optional, List, Any
from datetime import datetime

class ProductImageBase(BaseModel):
    image_url: str
    is_primary: bool = False
    order: int = 0

class ProductImageCreate(ProductImageBase):
    pass

class ProductImageResponse(ProductImageBase):
    id: str
    product_id: str
    created_at: datetime
    
    class Config:
        from_attributes = True

class ProductBase(BaseModel):
    title: str
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    currency: str = "USD"
    quantity: int = Field(1, ge=1)
    
    @validator('price')
    def price_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('El precio debe ser mayor que cero')
        return v

class ProductCreate(ProductBase):
    images: Optional[List[str]] = []

class ProductUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    currency: Optional[str] = None
    quantity: Optional[int] = None
    status: Optional[str] = None
    images: Optional[List[str]] = None
    
    @validator('price')
    def price_must_be_positive(cls, v):
        if v is not None and v <= 0:
            raise ValueError('El precio debe ser mayor que cero')
        return v
    
    @validator('status')
    def status_must_be_valid(cls, v):
        if v is not None and v not in ["active", "sold", "unavailable"]:
            raise ValueError('El estado debe ser "active", "sold" o "unavailable"')
        return v

class ProductResponse(ProductBase):
    id: str
    seller_id: str
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None
    images: List[ProductImageResponse] = []
    
    class Config:
        from_attributes = True