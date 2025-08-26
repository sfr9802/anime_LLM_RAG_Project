# configure/config.py
from __future__ import annotations
import os
from pathlib import Path

# ── .env 로더 (dotenv 없으면 수동 파싱) ─────────────────────────────────────
def _load_env_file(path: Path) -> None:
    try:
        from dotenv import load_dotenv  # python-dotenv
    except Exception:
        # 수동 파서: KEY=VALUE 줄만 읽어서 os.environ에 채움
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and (k not in os.environ):
                    os.environ[k] = v
        return
    else:
        load_dotenv(dotenv_path=path, override=False)

# 항상 이 파일 기준으로 app/app/.env를 로드 (OS env 우선, .env는 보충)
ENV_PATH = Path(__file__).resolve().parent / ".env"
_load_env_file(ENV_PATH)

def _env(*keys: str, default: str | None = None) -> str | None:
    """여러 키 중 먼저 발견되는 환경변수를 반환 (빈 문자열은 무시)."""
    for k in keys:
        v = os.getenv(k)
        if v is not None and str(v).strip() != "":
            return v
    return default

# --- Mongo ---
MONGO_URI = _env(
    "MONGO_URI",
    default="mongodb://raguser:ragpass@localhost:27017/?authSource=clean_namu_crawl",
)
MONGO_DB         = _env("MONGO_DB",         default="clean_namu_crawl")
MONGO_RAW_COL    = _env("MONGO_RAW_COL",    default="pages")
MONGO_CHUNK_COL  = _env("MONGO_CHUNK_COL",  default="chunks")

# --- Vector / Embedding ---
# SSD 경로 우선: CHROMA_DB_DIR > CHROMA_PATH > 기본값
CHROMA_DB_DIR     = _env("CHROMA_DB_DIR", "CHROMA_PATH", default="C:/chroma/namu_v3")
CHROMA_COLLECTION = _env("CHROMA_COLLECTION", default="namu_anime_v3")
CHROMA_SPACE      = _env("CHROMA_SPACE",      default="cosine")

# 임베딩 설정은 RAG_ 접두 우선, 없으면 기존 키
EMBED_MODEL    = _env("RAG_EMBED_MODEL", "EMBED_MODEL", default="BAAI/bge-m3")
EMBED_BATCH    = int(_env("RAG_EMBED_BATCH", "EMBED_BATCH", default="32"))
INDEX_BATCH    = int(_env("INDEX_BATCH", default="128"))
TOP_K          = int(_env("TOP_K", default="8"))
VECTOR_BACKEND = _env("VECTOR_BACKEND", default="chroma").lower()
SUMM_MODEL     = _env("SUMM_MODEL", default="")

# --- LLM provider switch ---
# 하위호환: 'local-http' -> 'local_http'
LLM_PROVIDER      = (_env("LLM_PROVIDER", default="local_http") or "local_http").replace("-", "_").lower()

# 로컬 HTTP (llama.cpp OpenAI 호환)
LLM_BASE_URL      = _env("LLM_BASE_URL", "LOCAL_LLM_BASE_URL", default="http://127.0.0.1:8000/v1")
LLM_MODEL_ALIAS   = _env("LLM_MODEL_ALIAS", "LOCAL_LLM_MODEL", default="gemma-2-9b-it")
LOCAL_LLM_TIMEOUT = float(_env("LOCAL_LLM_TIMEOUT", default="60"))

# 로컬 in-process
LLAMA_MODEL_PATH    = _env("LLAMA_MODEL_PATH", default=r"C:/llm/gguf/gemma-2-9b-it-Q4_K_M-fp16.gguf")
LLAMA_CTX           = int(_env("LLAMA_CTX", default="8192"))
LLAMA_N_GPU_LAYERS  = int(_env("LLAMA_N_GPU_LAYERS", default="-1"))

# OpenAI (real)
OPENAI_BASE_URL   = _env("OPENAI_BASE_URL", default="https://api.openai.com/v1")
OPENAI_API_KEY    = _env("OPENAI_API_KEY",  default="")
OPENAI_MODEL      = _env("OPENAI_MODEL",    default="gpt-4o-mini")
OPENAI_TIMEOUT    = float(_env("OPENAI_TIMEOUT", default="60"))
