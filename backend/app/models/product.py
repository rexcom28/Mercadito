from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Float, Table, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.db.base_class import Base
import uuid
from datetime import datetime

class Product(Base):
    __tablename__ = "products"
    
    id = Column(String, primary_key=True, index=True, default=lambda: str(uuid.uuid4()))
    title = Column(String, index=True, nullable=False)
    description = Column(String, nullable=True)
    price = Column(Float, nullable=False)
    currency = Column(String, default="USD")
    quantity = Column(Integer, default=1)
    status = Column(String, default="active")  # active, sold, unavailable
    seller_id = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relaciones
    seller = relationship("User", back_populates="products")
    images = relationship("ProductImage", back_populates="product", cascade="all, delete-orphan")
    offers = relationship("Offer", back_populates="product", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="product")
    
    # Índices adicionales para optimizar búsquedas
    __table_args__ = (
        Index('idx_product_status', 'status'),
        Index('idx_product_price', 'price'),
        Index('idx_product_created_at', 'created_at'),
        Index('idx_product_seller_status', 'seller_id', 'status'),
        Index('idx_product_price_status', 'price', 'status'),
    )