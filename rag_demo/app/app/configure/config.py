# configure/config.py
import os
from dotenv import load_dotenv
load_dotenv()

# --- Mongo ---
MONGO_URI = os.getenv("MONGO_URI", "mongodb://root:rootpass@localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "namu_crawl")
MONGO_RAW_COL = os.getenv("MONGO_RAW_COL", "pages")
MONGO_CHUNK_COL = os.getenv("MONGO_CHUNK_COL", "chunks")

# --- Vector / Embedding ---
CHROMA_PATH = os.getenv("CHROMA_PATH", "./data/chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "namu-anime")
EMBED_MODEL = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_BATCH = int(os.getenv("EMBED_BATCH", "32"))
INDEX_BATCH = int(os.getenv("INDEX_BATCH", "128"))
TOP_K = int(os.getenv("TOP_K", "6"))
VECTOR_BACKEND = os.getenv("VECTOR_BACKEND", "chroma").lower()
SUMM_MODEL = os.getenv("SUMM_MODEL", "")

# --- LLM provider switch ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "local-http").lower()  # local-http | local-inproc | openai

# Local HTTP (llama.cpp server)
LOCAL_LLM_BASE_URL = os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
LOCAL_LLM_API_KEY = os.getenv("LOCAL_LLM_API_KEY", "sk-local")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL", "gemma-2-9b-it")
LOCAL_LLM_TIMEOUT = float(os.getenv("LOCAL_LLM_TIMEOUT", "60"))

# Local in-process
LLAMA_MODEL_PATH = os.getenv("LLAMA_MODEL_PATH", r"C:/llm/gguf/gemma-2-9b-it-Q4_K_M-fp16.gguf")
LLAMA_CTX = int(os.getenv("LLAMA_CTX", "8192"))
LLAMA_N_GPU_LAYERS = int(os.getenv("LLAMA_N_GPU_LAYERS", "-1"))

# OpenAI (real)
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT", "60"))
