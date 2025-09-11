# 🧠 Anime RAG Stack — Full Pipeline Portfolio

도메인 특화 **Retrieval-Augmented Generation (RAG)** 백엔드 (애니메이션 문서 기반).  
데이터 크롤링부터 벡터 DB 튜닝, LLM 프롬프트 설계, 보안 API 디자인까지 구현.

## 🏗️ 아키텍처 개요
```
[ React ] ⇄ [ Spring Security 미들웨어 (OAuth2 + JWT + Redis) ] ⇄ [ FastAPI Core (Mongo + Chroma) ] ⇄ [ LLM (Gemma-2-9b-it) ]
```

- 엔드투엔드 플로우: 질의(Query) → 임베딩 → 검색(Retrieval) → MMR → 재랭킹 → 프롬프트 → LLM 응답  
- **Docker Compose** 기반으로 로컬 개발, GPU 추론, 모듈형 오케스트레이션 지원.
 
## ⚙️ Configuration

로컬 개발과 `docker-compose` 배포 환경에 맞춰 설정 파일을 분리했습니다.

- **로컬**: `.env.local`과 기본 `application.yml`을 `.env`와 함께 사용
- **Docker**: `.env.docker`와 `application-docker.yml`을 사용하며 `SPRING_PROFILES_ACTIVE=docker`

각 환경에 맞는 파일을 `.env`로 복사한 뒤 서비스를 실행하세요.

---

## 🔍 Core Projects

### 1. RAG Backend API (2025)

> FastAPI 기반 모듈화된 RAG 백엔드. 검색/재랭킹/응답 생성을 모두 지원.

- `/rag/ask`: 검색 기반 LLM 응답 생성
- `/rag/healthz`: 서비스 헬스체크

## 📈 Bench (2025-09-09, retrieval-only)

조건: `N=400`, `k=6`, `space=cosine`, `embed=BAAI/bge-m3 (L2 norm)`, `MMR(lam=0.5)`

| Metric        | Value | Baseline (BM25) | Notes                      |
|---------------|-------|-----------------|----------------------------|
| recall@5      | 0.56  | 0.42            | 튜닝 후 수치               |
| dup_rate      | 0.07  | -               | 제목/문서 ID 중복 기준     |
| p95 latency   | 50ms  | -               | `/rag/ask` 중 Retrieval 구간 |

**환경**: Ryzen 7 9800X3D / 64GB RAM / RTX 5080 (VRAM 16GB)  
※ 로컬 측정값으로, 클라우드/프로덕션 환경에서는 달라질 수 있습니다.

🧪 예시 요청:
```json
POST /rag/ask
{
  "question": "작품 A 등장인물",
  "k": 5,
  "use_mmr": true,
  "lam": 0.3
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
- 라이선스:
  - 원본: 나무위키  
  - 라이선스: `CC BY-NC-SA 2.0 KR`  
  - **비상업적 사용만 가능**, 파생물은 동일 라이선스로 공유해야 함

---

### 3. Spring Security Middleware

> React ⇄ FastAPI 사이 인증 및 프록시 담당 Spring 모듈

- OAuth2 팝업 로그인 → JWT 발급
- Redis 기반 Refresh Token + 블랙리스트 로그아웃
- `@AuthenticationPrincipal` 타입 분리 처리 (OAuth2 vs JWT)
- React에서 받은 토큰을 Axios global header에 설정

---

## 📮 API 개요

이 RAG 백엔드는 **검색 기반 답변 생성**을 위한 최소 엔드포인트만 노출합니다.

### 🔗 엔드포인트

| Path          | Method | Description                          |
|---------------|--------|--------------------------------------|
| `/rag/ask`    | POST   | End-to-end RAG (retrieval → LLM 답변) |
| `/rag/healthz`| GET    | 헬스체크 (서비스 가용성 확인)          |

> 🔒 인증: `Authorization: Bearer <token>` 필요 (Spring Security 미들웨어에서 JWT 검증)

### ✅ 요청/응답 예시

#### 요청
```http
POST /rag/ask?k=6&use_mmr=true&lam=0.5&max_tokens=512&temperature=0.2&preview_chars=600 HTTP/1.1
Authorization: Bearer ACCESS
Content-Type: application/json

{
  "question": "신이 된 히로인의 서사가 있는 애니메이션은?"
}
```

#### 응답 (`RAGQueryResponse`)
```json
{
  "question": "신이 된 히로인의 서사가 있는 애니메이션은?",
  "answer": "스즈미야 하루히의 우울",
  "documents": [
    { "id": "doc1#0", "title": "스즈미야 하루히의 우울", "score": 0.83, "text": "..." }
  ]
}
```

📁 관련 코드
```txt
app/
└── api/
    └── rag_router.py   ← /rag/ask, /rag/healthz
```

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

## 🖥️ UI 시연 자료 (Screenshots)

> 성능 지표 안정화 이후 실제 화면 캡처 추가 예정.

- 로그인 팝업 (OAuth2 → JWT)  
  ![login](/image/ui_login_placeholder.png)

- 대화형 RAG 화면 (질문/답변 + 참조 문서)  
  ![chat](/image/ui_chat.png)

---

## 🔭 Roadmap

### ✅ Done
- **데이터 수집/정제**
  - 나무위키 애니메이션 문서 7,700건 크롤링 (2006~2025)
  - 등장인물/설정 등 하위 링크 재귀 수집
  - 라이선스/푸터/광고 제거
  - 섹션/문단 기반 청킹 (평균 350 tokens)
  - Hugging Face 데이터셋 공개 ([namuwiki_anime](https://huggingface.co/datasets/ArinNya/namuwiki_anime))
- **벡터 DB & 검색**
  - Chroma 기반 검색 구축
  - MMR(Minimal Marginal Relevance) 적용
  - BM25 대비 성능 개선 (recall@5: 0.3 → 0.56, 2025-09-10 기준)
  - Optuna 기반 파라미터 튜닝 환경 구성
- **LLM 연동**
  - Gemma-2-9b-it 모델 로컬 추론 (docker 사용한 모델 서빙, http 사용하여 호출)
  - RAG 프롬프트 설계 (Jinja2 기반)
  - Retrieval 결과를 LLM 응답으로 연결
- **백엔드**
  - FastAPI 모듈화: `/rag/ask`, `/rag/healthz`
  - 성능/품질 지표 API 제공 (recall, dup_rate, p95, nDCG 등)
- **미들웨어 & 인증**
  - Spring Security OAuth2 로그인 → JWT 발급
  - Redis 기반 Refresh Token & 블랙리스트 로그아웃
  - `@AuthenticationPrincipal` 타입 분리 (OAuth2 vs JWT)
  - React ↔ Spring ↔ FastAPI 프록시 플로우 완성
- **프론트엔드**
  - React GPT-style 대화창 UI (기초 버전)
  - OAuth2 팝업 로그인 처리
  - Axios global header에 토큰 자동 반영
- **배포/환경**
  - Docker Compose 기반 로컬 개발 환경
  - GPU 추론 지원 (RTX 5080)

---

### 🔄 In Progress
- Optuna 기반 파라미터 고도화 (`fetch_k`, `mmr_k`, `rerank_in` 등)
- RAG 품질 튜닝 및 실험 결과 정리
- UI 개선 (참조 문서 하이라이팅, 시각화)

---

### 🔭 Next
- 사용자 검색 로그 기록 및 분석 기능
- 로컬 + 클라우드 하이브리드 서빙 환경 구축
- 추가 데이터셋 확장 (애니메이션 관련 다른 문서 탐색, ex. 픽시브 이미지 태그 등)

---

## 📎 Links

- **Blog**: [기술 아키텍처 및 구현 기록](https://arin-nya.tistory.com/)
- **Dataset**: [NamuWiki Anime RAG Dataset](https://huggingface.co/datasets/ArinNya/namuwiki_anime)
- **Collections**: `collections/rag-demo.json`
