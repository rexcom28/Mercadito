from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class MessageBase(BaseModel):
    recipient_id: str
    content: str
    related_product_id: Optional[str] = None

class MessageCreate(MessageBase):
    pass

class MessageResponse(MessageBase):
    id: str
    sender_id: str
    is_read: bool
    created_at: datetime
    
    class Config:
        from_attributes = True