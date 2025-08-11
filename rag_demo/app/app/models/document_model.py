# models/document_model.py
from models.base import AppBaseModel

class DocumentItem(AppBaseModel):
    id: str                    # "{pageId}#{chunkIdx}"
    page_id: str | None = None
    chunk_id: str | None = None
    url: str | None = None
    title: str | None = None
    section: str | None = None
    seed: str | None = None
    score: float | None = None # 1 - cosine_distance 등
    text: str
