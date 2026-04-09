"""Central router registration."""
from fastapi import FastAPI
from app.api.routes import admin, debug, health, query, rag, search

def register_routers(app: FastAPI) -> None:
    app.include_router(health.router)
    app.include_router(rag.router)
    app.include_router(query.router)
    app.include_router(search.router)
    app.include_router(admin.router)
    app.include_router(debug.router)
