# app/db_connection/mongo_client.py
import os
from typing import Optional
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database
from dotenv import load_dotenv

# 로컬 .env 로드 → 환경변수 우선
load_dotenv()

# 환경 변수 / 기본값
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB  = os.getenv("MONGO_DB",  "arin")

# 내부 싱글턴 상태
_client: Optional[MongoClient] = None
_db: Optional[Database] = None


def _build_client() -> MongoClient:
    """MongoClient 생성 옵션 한 곳에 모음."""
    return MongoClient(
        MONGO_URI,
        serverSelectionTimeoutMS=5000,  # 초기 커넥션/핑 타임아웃
        socketTimeoutMS=10000,
        maxPoolSize=50,
        retryWrites=True,
        uuidRepresentation="standard",
    )


def get_client() -> MongoClient:
    """프로세스 전역에서 재사용할 MongoClient (지연 초기화)."""
    global _client
    if _client is None:
        _client = _build_client()
    return _client


def get_db(name: Optional[str] = None) -> Database:
    """
    기본 DB 핸들 반환. name을 주면 해당 DB 핸들을 반환.
    지연 초기화 + 캐싱.
    """
    global _db
    if name:
        return get_client()[name]
    if _db is None:
        _db = get_client()[MONGO_DB]
    return _db


def get_collection(name: str, db: Optional[Database] = None) -> Collection:
    """컬렉션 헬퍼."""
    database = db or get_db()
    return database[name]


def ping() -> bool:
    """연결 헬스체크 (몽고 5+ 권장: admin ping)."""
    try:
        get_client().admin.command("ping")
        return True
    except Exception:
        return False


def close_client() -> None:
    """애플리케이션 종료 시 명시적으로 풀 닫고 싶을 때."""
    global _client, _db
    if _client is not None:
        _client.close()
    _client = None
    _db = None
