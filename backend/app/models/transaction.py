from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base_class import Base
import uuid
from datetime import datetime

class Transaction(Base):
    __tablename__ = "transactions"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String, ForeignKey("products.id"), nullable=False)
    buyer_id = Column(String, ForeignKey("users.id"), nullable=False)
    seller_id = Column(String, ForeignKey("users.id"), nullable=False)
    offer_id = Column(String, ForeignKey("offers.id"), nullable=True)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    status = Column(String, default="pending")  # pending, processing, completed, cancelled, refunded
    payment_method = Column(String, nullable=True)
    payment_id = Column(String, nullable=True)  # ID externo del procesador de pagos
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relaciones
    product = relationship("Product", back_populates="transactions")
    buyer = relationship("User", foreign_keys=[buyer_id], back_populates="purchases")
    seller = relationship("User", foreign_keys=[seller_id], back_populates="sales")
    offer = relationship("Offer")
    
    # Índices
    __table_args__ = (
        Index('idx_transaction_status', 'status'),
        Index('idx_transaction_buyer', 'buyer_id'),
        Index('idx_transaction_seller', 'seller_id'),
        Index('idx_transaction_created_at', 'created_at'),
    )