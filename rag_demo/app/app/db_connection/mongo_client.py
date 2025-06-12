
from pymongo import MongoClient
from pymongo.collection import Collection
import os
from configure import config

MONGO_URI = os.getenv("mongo_uri", config.MONGO_URL)
DB_NAME = os.getenv("mongo", config.DB_NAME)
COLLECTION_NAME = os.getenv("mgcl", config.COLLECTION_NAME)

_client : MongoClient = None
_collection : Collection = None

def get_mongo_client() -> MongoClient:
    global _client
    if _client is None:
        _client = MongoClient(MONGO_URI, maxPoolSize=10)
    return _client

def get_collection() -> Collection:
    global _collection
    if _collection is None:
        client = get_mongo_client()
        _collection = client[DB_NAME][COLLECTION_NAME]
    return _collection
