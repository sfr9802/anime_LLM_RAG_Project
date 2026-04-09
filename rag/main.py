"""Arin RAG application entry point."""
from __future__ import annotations

import logging

from fastapi import FastAPI

from app.runtime.config import Settings
from app.runtime.lifespan import build_lifespan
from app.runtime.bootstrap import build_service_container
from app.api.router import register_routers
from app.api.exception_handlers import register_exception_handlers


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory."""
    app_settings = settings or Settings()

    logging.basicConfig(level=app_settings.log_level.upper())

    application = FastAPI(
        title="Arin RAG",
        version="0.2.0",
        lifespan=build_lifespan(app_settings),
    )

    application.state.settings = app_settings
    application.state.services = build_service_container(app_settings)

    register_exception_handlers(application)
    register_routers(application)

    return application


app = create_app()
