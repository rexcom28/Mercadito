from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base_class import Base
import uuid
from datetime import datetime

class Offer(Base):
    __tablename__ = "offers"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    product_id = Column(String, ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    buyer_id = Column(String, ForeignKey("users.id"), nullable=False)
    seller_id = Column(String, ForeignKey("users.id"), nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    status = Column(String, default="pending")  # pending, accepted, rejected, expired
    message = Column(String, nullable=True)
    expires_at = Column(DateTime(timezone=True), index=True)  # Indexado para búsqueda eficiente de ofertas expiradas
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    version = Column(Integer, default=1)  # Para control de concurrencia optimista
    
    # Relaciones
    product = relationship("Product", back_populates="offers")
    buyer = relationship("User", foreign_keys=[buyer_id], back_populates="offers_made")
    seller = relationship("User", foreign_keys=[seller_id], back_populates="offers_received")
    
    # Índices adicionales
    __table_args__ = (
        Index('idx_offer_product_status', 'product_id', 'status'),
        Index('idx_offer_buyer_status', 'buyer_id', 'status'),
        Index('idx_offer_seller_status', 'seller_id', 'status'),
        Index('idx_offer_expires_at_status', 'expires_at', 'status'),
    )