
# 🧠 Anime RAG Stack — Full Pipeline Portfolio

Domain-specialized **Retrieval-Augmented Generation (RAG)** backend for anime documents.  
From data crawling to vector DB tuning, LLM prompting, and secure API design.

## 🏗️ Architecture Overview

```
[ React ] ⇄ [ Spring Security Middleware (OAuth2 + JWT + Redis) ] ⇄ [ FastAPI Core (Mongo + Chroma) ] ⇄ [ LLM (Gemma-2-9b-it) ]
```

- End-to-end flow: Query → Embedding → Retrieval → MMR → Rerank → Prompt → LLM Response  
- Built with **Docker Compose** for local development, GPU inference, and modular orchestration.

---

## 🔍 Core Projects

### 1. RAG Backend API (2025)

> FastAPI 기반 모듈화된 RAG 백엔드. 검색/재랭킹/응답 생성을 모두 지원.

- `/ingest`: 문서 업서트 (Mongo + Chroma)
- `/retrieve`: 임베딩 검색 + (선택) MMR
- `/ask`: 검색 기반 LLM 응답 생성


📈 **현재 품질 지표** (2025-09-09 기준):
- recall@5: `0.30`
- dup_rate: `0.07`
- p95 latency: `50ms`

🧪 예시 요청:
```json
POST /retrieve
{
  "query": "작품 A 등장인물",
  "k": 5,
  "use_mmr": true,
  "lambda_": 0.3
}
```

---

### 2. NamuWiki Crawler & Cleaner

> 나무위키 기반 대규모 문서 수집 및 전처리 → RAG 최적화 JSONL 생성.

- 크롤링 대상: 애니메이션 관련 문서 7,700건 (2006~2025)
- 주요 처리:
  - 등장인물/설정 등 하위 링크 재귀 수집
  - 라이선스/푸터/광고 제거
  - 섹션/문단 기반 청킹, avg chunk ≈ 350 tokens
- 결과:
  - Hugging Face 데이터셋 공개  
    → [NamuWiki Anime RAG Dataset](https://huggingface.co/datasets/ArinNya/namuwiki_anime)

---

### 3. Spring Security Middleware

> React ⇄ FastAPI 사이 인증 및 프록시 담당 Spring 모듈

- OAuth2 팝업 로그인 → JWT 발급
- Redis 기반 Refresh Token + 블랙리스트 로그아웃
- `@AuthenticationPrincipal` 타입 분리 처리 (OAuth2 vs JWT)
- React에서 받은 토큰을 Axios global header에 설정

---

## 📮 API Overview

This RAG backend exposes modular endpoints for **retrieval**, **LLM answering**, **debugging**, and **admin ingestion**.  
You can interact via `/rag/*`, `/debug/*`, and `/admin/ingest/*` routes.

### 🔗 주요 엔드포인트 요약

| Path | Method | Description |
|------|--------|-------------|
| `/rag/ask` | `POST` | End-to-end RAG (search + LLM answer) |
| `/rag/query` | `POST` | Retrieval only |
| `/rag/query/debug` | `POST` | Retrieval + document context |
| `/exp/search` | `POST` | Direct embedding search |
| `/debug/retrieve` | `POST` | Internal vector search API |
| `/debug/eval_hit` | `POST` | Eval goldset against vector DB |
| `/debug/rag-ask` | `POST` | RAG answer (internal) |
| `/admin/ingest/start` | `POST` | Start ingestion job |
| `/admin/ingest/{job_id}` | `GET` | Check ingestion status |

📁 관련 코드 위치:
```txt
├── app/
│   └── api/
│       ├── rag_router.py        ← /rag/ask, /rag/healthz
│       ├── query_router.py      ← /rag/query
│       ├── search_router.py     ← /exp/search
│       ├── debug_router.py      ← /debug/*
│       └── admin_ingest_router.py ← /admin/ingest/*
```

### 🔍 `/rag/ask` 요청/응답 예시

`/rag/ask` 엔드포인트는 본문(JSON)으로 **질문**을 받고, 선택적인 **하이퍼파라미터**는 쿼리 스트링을 통해 전달받습니다.  
아래는 기본값을 포함한 요청 예시입니다:

#### ✅ 요청 예시
```http
POST /rag/ask?k=6&use_mmr=true&lam=0.5&max_tokens=512&temperature=0.2&preview_chars=600 HTTP/1.1
Authorization: Bearer ACCESS
Content-Type: application/json

{
  "question": "신이 된 히로인의 서사가 있는 애니메이션은?"
}
```

#### ✅ 응답 예시 (`RAGQueryResponse`)
```json
{
  "question": "신이 된 히로인의 서사가 있는 애니메이션은?",
  "answer": "스즈미야 하루히의 우울",
  "documents": [
    {
      "id": "doc1#0",
      "title": "스즈미야 하루히의 우울",
      "score": 0.83,
      "text": "..."
    },
    ...
  ]
}
```

- `question`: 사용자로부터 입력받은 질문 원문
- `answer`: 검색된 문서를 기반으로 LLM이 생성한 응답
- `documents`: 검색 결과로 사용된 top-k 문서 목록 (`title`, `score`, `text` 등 포함)

> 🔒 요청 시 `Authorization: Bearer <token>` 헤더를 포함해야 하며, 미들웨어에서 JWT 유효성 검사를 수행합니다.

---

## 🖼️ Sequence Diagrams

#### 🔐 로그인 흐름 (OAuth2 → JWT → OTC 발급)

![로그인](/image/auth_login_flow.png)

#### 🔁 API 요청 흐름 (프록시 + Redis 블랙리스트 검증)

![리버스프록시](/image/auth_proxy_flow.png)

#### 🚪 로그아웃 흐름 (Redis 블랙리스트 + Refresh 삭제)

![로그아웃](/image/auth_logout_flow.png)

#### 🔄 Ask API 전체 흐름

> `/rag/ask` → 문서 검색 → LLM 응답 → JSON 반환

![FastAPI](/image/rag_ask_flow.png)

---

## ⚙️ Tech Highlights

- 💡 **MMR Re-ranking**: Semantic 다양성 보장, 중복 제거
- ✂️ **Chunking Strategy**: 한국어 종결어미/제목 기반 청킹
- 🧪 **Benchmark APIs**: recall@k, dup_rate, p95 등 측정 가능
- 🔁 **Embeddings**: bge-m3 실험

---

## 🔭 Roadmap

- [ ] RAG 응답 품질 향상을 위한 파라미터 튜닝 고도화 (Optuna 기반)
- [ ] Chroma 벡터 검색 Top-K 튜닝: `fetch_k`, `mmr_k`, `rerank_in` 최적화
- [ ] 프론트엔드 대화형 UI 개선 (GPT 스타일 대화창 + 하이라이팅 처리)
- [ ] 사용자 입력 기반 검색 로그 기록 + 분석 기능 추가
- [ ] 검색 리콜/중복률/응답시간 지표 시각화 및 비교 리포트 정리

---

## 📎 Links

- **Blog**: [기술 아키텍처 및 구현 기록](https://arin-nya.tistory.com/)
- **Dataset**: [NamuWiki Anime RAG Dataset](https://huggingface.co/datasets/ArinNya/namuwiki_anime)
- **Collections**: `collections/rag-demo.json`
