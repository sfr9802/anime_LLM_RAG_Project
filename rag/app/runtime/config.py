"""Application configuration using pydantic-settings."""
from __future__ import annotations
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    chroma_db_dir: str = "C:/chroma/namu_v3"
    chroma_collection: str = "namu_anime_v3"
    chroma_space: str = "cosine"
    vector_backend: str = "chroma"
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "clean_namu_crawl"
    mongo_raw_col: str = "works"
    mongo_chunk_col: str = "characters"
    embed_model: str = "BAAI/bge-m3"
    rag_embed_model: str = ""
    rag_embed_batch: int = 64
    embed_batch: int = 64
    index_batch: int = 500
    top_k: int = 6
    llm_provider: str = "local_http"
    llm_base_url: str = "http://localhost:8000/v1"
    llm_model_alias: str = "gemma-2-9b-it"
    jwt_secret: str = ""
    jwt_secret_b64: str = "false"
    jwt_aud: str = "frontend"
    jwt_iss: str = "arin"
    log_level: str = "INFO"

    @property
    def effective_embed_model(self) -> str:
        return self.rag_embed_model or self.embed_model
