"""Request schemas."""
from pydantic import BaseModel, ConfigDict

class QueryRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    question: str

class SearchRequest(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    query: str
    top_k: int = 6
