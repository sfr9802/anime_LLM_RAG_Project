"""FastAPI lifespan context manager."""
from __future__ import annotations
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.runtime.config import Settings

logger = logging.getLogger(__name__)

def build_lifespan(settings: Settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("Starting Arin RAG (embed=%s, llm=%s)", settings.effective_embed_model, settings.llm_provider)
        yield
        logger.info("Shutting down Arin RAG")
    return lifespan
