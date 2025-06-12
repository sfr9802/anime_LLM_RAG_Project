from pydantic import BaseModel

class QueryRequest(BaseModel) :
    question: str
    
class QueryResponse(BaseModel) :
    question : str
    answer : str
    
class SearchRequest(BaseModel):
    query: str
    top_k : int = 3    
    
class SearchResult(BaseModel):
    doc_id: str
    content: str
    score : float

class SearchResponse(BaseModel):
    result : list[SearchResult]