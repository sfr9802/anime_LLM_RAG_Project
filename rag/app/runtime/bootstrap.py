"""Service container and dependency assembly."""
from __future__ import annotations
from dataclasses import dataclass
from app.runtime.config import Settings

@dataclass(slots=True)
class ServiceContainer:
    settings: Settings

def build_service_container(settings: Settings) -> ServiceContainer:
    return ServiceContainer(settings=settings)
