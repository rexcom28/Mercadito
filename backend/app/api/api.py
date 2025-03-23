#backend/app/api/v1/api.py
from fastapi import APIRouter
from app.api.v1.endpoints import users, products, offers, messages, transactions

api_router = APIRouter()

# Incluir routers para diferentes recursos
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(products.router, prefix="/products", tags=["products"])
api_router.include_router(offers.router, prefix="/offers", tags=["offers"])
api_router.include_router(messages.router, prefix="/messages", tags=["messages"])
api_router.include_router(transactions.router, prefix="/transactions", tags=["transactions"])