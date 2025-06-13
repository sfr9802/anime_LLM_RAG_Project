from typing import Optional
from models.base import AppBaseModel

class DocumentItem(AppBaseModel):
    text: str
    source: Optional[str] = None
    title: Optional[str] = None
