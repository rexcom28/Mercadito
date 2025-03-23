from pydantic import BaseModel, validator, Field
from typing import Optional, List
from datetime import datetime

class OfferBase(BaseModel):
    product_id: str
    amount: float = Field(..., gt=0)
    message: Optional[str] = None
    
    @validator('amount')
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('El monto debe ser mayor que cero')
        return v

class OfferCreate(OfferBase):
    pass

class OfferUpdate(BaseModel):
    status: str
    
    @validator('status')
    def status_must_be_valid(cls, v):
        if v not in ["accepted", "rejected"]:
            raise ValueError('El estado debe ser "accepted" o "rejected"')
        return v

class OfferResponse(OfferBase):
    id: str
    buyer_id: str
    seller_id: str
    currency: str
    status: str
    expires_at: datetime
    created_at: datetime
    updated_at: Optional[datetime] = None
    version: int
    
    class Config:
        from_attributes = True