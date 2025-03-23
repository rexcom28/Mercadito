from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Table, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base_class import Base
import uuid
from datetime import datetime

class User(Base):
    __tablename__ = "users"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    full_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_seller = Column(Boolean, default=False)
    phone = Column(String, nullable=True)
    profile_image = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relaciones
    products = relationship("Product", back_populates="seller")
    received_messages = relationship("Message", foreign_keys="Message.recipient_id", back_populates="recipient")
    sent_messages = relationship("Message", foreign_keys="Message.sender_id", back_populates="sender")
    offers_made = relationship("Offer", foreign_keys="Offer.buyer_id", back_populates="buyer")
    offers_received = relationship("Offer", foreign_keys="Offer.seller_id", back_populates="seller")
    purchases = relationship("Transaction", foreign_keys="Transaction.buyer_id", back_populates="buyer")
    sales = relationship("Transaction", foreign_keys="Transaction.seller_id", back_populates="seller")
    
    # Índices adicionales para optimizar búsquedas
    __table_args__ = (
        Index('idx_user_is_seller', 'is_seller'),
        Index('idx_user_fullname', 'full_name'),
        Index('idx_user_created_at', 'created_at'),
    )