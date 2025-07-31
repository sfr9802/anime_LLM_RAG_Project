from fastapi import FastAPI
from router import query_router  # 예시

app = FastAPI()

# 빠짐 → 여기서 router 등록 안 하면 /query 인식 못 함
app.include_router(query_router)