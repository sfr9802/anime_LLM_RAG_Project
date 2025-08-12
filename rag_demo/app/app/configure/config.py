# configure/config.py
import os
from dotenv import load_dotenv

load_dotenv()

# Mongo
MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://root:rootpass@localhost:27017")
MONGO_DB: str = os.getenv("MONGO_DB", "namu_crawl")
MONGO_RAW_COL: str = os.getenv("MONGO_RAW_COL", "pages")
MONGO_CHUNK_COL: str = os.getenv("MONGO_CHUNK_COL", "chunks")

# Chroma
CHROMA_PATH: str = os.getenv("CHROMA_PATH", "./data/chroma")
CHROMA_COLLECTION: str = os.getenv("CHROMA_COLLECTION", "namu-anime")

# Embedding & index
EMBED_MODEL: str = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_BATCH: int = int(os.getenv("EMBED_BATCH", "32"))
INDEX_BATCH: int = int(os.getenv("INDEX_BATCH", "128"))

# Search
TOP_K: int = int(os.getenv("TOP_K", "6"))
VECTOR_BACKEND: str = os.getenv("VECTOR_BACKEND", "chroma").lower()  # "faiss"|"chroma"

SUMM_MODEL: str = os.getenv("SUMM_MODEL", "")
