from pydantic import BaseModel, validator, Field
from typing import Optional
from datetime import datetime

class TransactionBase(BaseModel):
    product_id: str
    amount: float = Field(..., gt=0)
    payment_method: Optional[str] = None
    
    @validator('amount')
    def amount_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('El monto debe ser mayor que cero')
        return v

class TransactionCreate(TransactionBase):
    offer_id: Optional[str] = None

class TransactionResponse(TransactionBase):
    id: str
    buyer_id: str
    seller_id: str
    offer_id: Optional[str] = None
    currency: str
    status: str
    payment_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True