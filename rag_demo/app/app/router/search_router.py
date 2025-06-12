from fastapi import APIRouter
from models.api_io_dto import SearchRequest, SearchResponse, SearchResult
from vector_store import search_vectors

