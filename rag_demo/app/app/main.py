from fastapi import FastAPI
from router.query_router import router as query_route # 예시
from router.search_router import router as search_route
app = FastAPI()

# 빠짐 → 여기서 router 등록 안 하면 /query 인식 못 함
app.include_router(query_route)
app.include_router(search_route)