from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base_class import Base
import uuid

class Message(Base):
    __tablename__ = "messages"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    sender_id = Column(String, ForeignKey("users.id"), nullable=False)
    recipient_id = Column(String, ForeignKey("users.id"), nullable=False)
    content = Column(String, nullable=False)
    is_read = Column(Boolean, default=False)
    related_product_id = Column(String, ForeignKey("products.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    # Relaciones
    sender = relationship("User", foreign_keys=[sender_id], back_populates="sent_messages")
    recipient = relationship("User", foreign_keys=[recipient_id], back_populates="received_messages")
    related_product = relationship("Product")
    
    # Índices para optimizar búsqueda de conversaciones
    __table_args__ = (
        Index('idx_message_sender_recipient', 'sender_id', 'recipient_id'),
        Index('idx_message_recipient_read', 'recipient_id', 'is_read'),
        Index('idx_message_product', 'related_product_id'),
        Index('idx_message_created_at', 'created_at'),
    )