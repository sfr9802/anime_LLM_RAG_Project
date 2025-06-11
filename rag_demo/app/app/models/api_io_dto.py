from pydantic import BaseModel

class QueryRequest(BaseModel) :
    question: str
    
class QueryResponse(BaseModel) :
    question : str
    answer : str