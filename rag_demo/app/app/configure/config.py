import os
from dotenv import load_dotenv
load_dotenv()

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB  = os.getenv("MONGO_DB", "namu_crawl")
RAW_COL   = os.getenv("MONGO_RAW_COL", "pages")
CHUNK_COL = os.getenv("MONGO_CHUNK_COL", "chunks")

CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "namu-anime")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
TOP_K = int(os.getenv("TOP_K", "6"))

MONGO_URI: str = "mongodb://root:rootpass@localhost:27017"
MONGO_DB: str = "namu_crawl"
MONGO_RAW_COL: str = "pages"

CHROMA_PATH: str = "./data/chroma"
CHROMA_COLLECTION: str = "namu-anime"

EMBED_MODEL: str = "BAAI/bge-m3"
EMBED_BATCH: int = 32     # GPU 넉넉하니 64~128로 올려도 됨
INDEX_BATCH: int = 128