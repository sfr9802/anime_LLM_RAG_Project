# models/document_model.py
from typing import Optional
from typing_extensions import Annotated
from pydantic import Field
from .base import AppBaseModel

class DocumentItem(AppBaseModel):
    id: str                       # "{pageId}#{chunkIdx}"
    page_id: Optional[str] = None
    chunk_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    section: Optional[str] = None
    seed: Optional[str] = None
    score: Annotated[Optional[float], Field(ge=0, le=1)] = None
    text: Annotated[str, Field(min_length=1)]
