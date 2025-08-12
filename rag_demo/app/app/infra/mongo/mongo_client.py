# app/db_connection/mongo_client.py
import os
from pymongo import MongoClient
from configure import config
from dotenv import load_dotenv

load_dotenv()

# ✅ 이름 통일: 모두 대문자, config 백업값 사용
MONGO_URI = os.getenv("MONGO_URI", config.MONGO_URI)
MONGO_DB  = os.getenv("MONGO_DB",  config.MONGO_DB)

# 필요 시 옵션 추가 (time out 등)
mongo_client = MongoClient(MONGO_URI)
mongo_db = mongo_client[MONGO_DB]

# 컬렉션을 여기서 꺼내 쓸거면 명시
# RAW_COL   = os.getenv("MONGO_RAW_COL",   config.MONGO_RAW_COL)
# CHUNK_COL = os.getenv("MONGO_CHUNK_COL", config.MONGO_CHUNK_COL)
# raw_collection   = mongo_db[RAW_COL]
# chunk_collection = mongo_db[CHUNK_COL]
