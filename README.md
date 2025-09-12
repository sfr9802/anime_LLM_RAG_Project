# 🧠 Anime RAG Stack — Full Pipeline Portfolio

도메인 특화 **Retrieval-Augmented Generation (RAG)** 백엔드 (애니메이션 문서 기반).  
데이터 크롤링 → 벡터 DB 튜닝 → 프롬프트 설계 → 보안 API까지 **엔드-투-엔드**로 구현.
> - RawData, Vector DB, Prompt Template, Embedding Model 교체로 도메인 전환 가능  
> - 애니메이션 문서 외에도 내부 문서, 법률, 기술 FAQ 등 다양한 활용 가능성

> 📸 **Demo 스크린샷은 아래 _UI 시연 자료_ 섹션**에 배치했습니다. (빠르게 보고 싶다면 바로 스크롤 ↓)

## 🏗️ 아키텍처 개요
```
[ React ] ⇄ [ Spring Security 미들웨어 (OAuth2 + JWT + Redis) ] ⇄ [ FastAPI Core (Mongo + Chroma) ] ⇄ [ LLM (Gemma-2-9b-it) ]
```
- 엔드투엔드 플로우: 질의(Query) → 임베딩 → 검색(Retrieval) → MMR → 재랭킹 → 프롬프트 → LLM 응답  
- **Docker Compose** 기반으로 로컬 개발, GPU 추론, 모듈형 오케스트레이션 지원.

---

## ⚙️ Configuration

로컬 개발과 `docker-compose` 배포 환경에 맞춰 설정 파일을 분리.

- **로컬**: `.env.local`과 기본 `application.yml`을 `.env`와 함께 사용
- **Docker**: `.env.docker`와 `application-docker.yml` + `SPRING_PROFILES_ACTIVE=docker`

각 환경에 맞는 파일을 `.env`로 복사한 뒤 서비스를 실행하세요.

/models 디렉토리에 gemma-2-9b-it-Q4_K_M-fp16.gguf 모델이 필요합니다.

구글 GCP의 OAuth2 id/key pair 필요합니다.

---

## 🔍 Core Projects

### 1) RAG Backend API (2025)
> FastAPI 기반 모듈화된 RAG 백엔드. 검색/재랭킹/응답 생성을 지원.

- `/rag/ask`: 검색 기반 LLM 응답 생성
- `/rag/healthz`: 서비스 헬스체크

### 2) NamuWiki Crawler & Cleaner
> 나무위키 기반 대규모 문서 수집 및 전처리 → RAG 최적화 JSONL 생성.

- 대상: 애니메이션 관련 문서 7,700건 (2006~2025)
- 처리: 등장인물/설정 등 하위 링크 재귀 수집, 광고/푸터 제거, 섹션/문단 기반 청킹 (avg ≈ 350 tokens)
- 공개: Hugging Face 데이터셋 → [NamuWiki Anime RAG Dataset](https://huggingface.co/datasets/ArinNya/namuwiki_anime)
- 라이선스: 원본 `CC BY-NC-SA 2.0 KR` (비상업적, 동일조건변경허락)

### 3) Spring Security Middleware
> React ⇄ FastAPI 사이 인증 및 프록시 담당

- OAuth2 팝업 로그인 → JWT 발급
- Redis 기반 Refresh Token + 블랙리스트 로그아웃
- `@AuthenticationPrincipal` 타입 분리 (OAuth2 vs JWT)
- React에서 받은 토큰을 Axios global header에 설정

---

## 📮 API 개요

이 RAG 백엔드는 **검색 기반 답변 생성**을 위한 최소 엔드포인트만 노출합니다.

### 🔗 엔드포인트
| Path           | Method | Description                            |
|----------------|--------|----------------------------------------|
| `/rag/ask`     | POST   | End-to-end RAG (retrieval → LLM)       |
| `/rag/healthz` | GET    | 헬스체크 (서비스 가용성 확인)            |

> 🔒 인증: `Authorization: Bearer <token>` 필요 (Spring Security 미들웨어에서 JWT 검증)

### ✅ 요청/응답 예시
요청:
```http
POST /rag/ask?k=6&use_mmr=true&lam=0.5&max_tokens=512&temperature=0.2&preview_chars=600 HTTP/1.1
Authorization: Bearer ACCESS
Content-Type: application/json

{
  "question": "신이 된 히로인의 서사가 있는 애니메이션은?"
}
```
응답 (`RAGQueryResponse`):
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
```
app/
└── api/
    └── rag_router.py   ← /rag/ask, /rag/healthz
```

---

## 🖼️ Sequence Diagrams

### 🔐 로그인 흐름 (OAuth2 → JWT → OTC 발급)
![로그인](./image/auth_login_flow.png)

### 🔁 API 요청 흐름 (프록시 + Redis 블랙리스트 검증)
![리버스프록시](./image/auth_proxy_flow.png)

### 🚪 로그아웃 흐름 (Redis 블랙리스트 + Refresh 삭제)
![로그아웃](./image/auth_logout_flow.png)

### 🔄 Ask API 전체 흐름
> `/rag/ask` → 문서 검색 → LLM 응답 → JSON 반환
![FastAPI](./image/rag_ask_flow.png)

---

## 📈 Bench (2025-09-12, retrieval-only)

조건: N=400, k=8, space=cosine, embed=BAAI/bge-m3 (L2 norm), MMR(lam=0.65), match_by=title, distinct_by=title, reranker=keep

| Metric              | Value        |  Notes                               |
| ------------------- | ------------ | ----------------------------------- |
| **Hit\@8**          | **0.8421**   | 쿼리당 1개라도 정답 타이틀 매칭 시 1              |
| **Recall\@8**       | **0.8421**   | title 매칭 + title 단위 dedup 기준        |
| **MRR**             | **0.8264**   |                                     |
| **nDCG**            | **0.8494**   |                                     |
| **Recall\@50(raw)** | **0.8421**   | rerank/dedup 전 원시 Top-50 검색 기준      |
| **dup\_rate**       | **0.0000**   | 제목/문서 ID 중복 기준                      |
| **p95 latency**     | **178.29ms** | retrieval 모듈 기준(`/rag/ask` 중 검색 구간) |


**환경**: Ryzen 7 9800X3D / 64GB RAM / RTX 5080 (VRAM 16GB)  
※ 로컬 측정값. 클라우드/프로덕션과 다를 수 있음.
※ 본 수치는 by=title + distinct_by=title 평가축 결과입니다. by=doc/seed로 바꾸면 절대값은 낮아집니다.
---

## 🖥️ UI 시연 자료 (Screenshots)

**1) OAuth2 로그인 화면**  
![OAuth2 로그인](./image/oauth_login.png)

**2) OAuth 처리 성공 (팝업 자동 종료 직전)**  
![OAuth 처리 성공](./image/oauth_success.png)

**3) 메인 대화형 RAG UI**  
![메인 RAG UI](./image/app_main.png)

**3.1) 메인 대화형 RAG UI 테마 변경**  
![테마 변경](./image/app_main_white_theme.png)

**4) 실제 사용 UI**  
![실제 사용 UI](./image/ui_chat.png)

---

## ⚙️ Tech Highlights
- 💡 **MMR Re-ranking**: 다양성 보장, 중복 제거
- ✂️ **Chunking Strategy**: 한국어 종결어미/제목 기반 청킹
- 🧪 **Benchmark Utilities**: recall@k, dup_rate, p95 등
- 🔁 **Embeddings**: bge-m3 사용

---

## 🔭 Roadmap

### ✅ Done
- 데이터 수집/정제: 7,700건, 하위 링크 재귀, 광고/푸터 제거, 섹션/문단 청킹, HF 공개
- 벡터 DB & 검색: Chroma + MMR, BM25 대비 개선, Optuna 튜닝 환경
- LLM 연동: Gemma-2-9b-it 로컬 서빙, Jinja2 프롬프트
- 백엔드: FastAPI `/rag/ask`, `/rag/healthz`, 품질/성능 지표 유틸
- 미들웨어 & 인증: OAuth2 → JWT, Redis Refresh/Blacklist, React↔Spring↔FastAPI 프록시
- 프론트엔드: GPT-style 대화 UI, OAuth2 팝업 처리, Axios 헤더 자동화
- 배포/환경: Docker Compose, GPU 추론

### 🔄 In Progress
- Optuna 기반 파라미터 고도화 (`fetch_k`, `mmr_k`, `rerank_in`…)
- RAG 품질 튜닝 및 실험 결과 문서화
- UI 개선 (참조 문서 하이라이트 등)

### 🔭 Next
- 사용자 검색 로그/분석
- 로컬+클라우드 하이브리드 서빙
- 데이터셋 확장 (ex. 픽시브 태그)

---

## 📎 Links
- **Blog**: [기술 아키텍처 및 구현 기록](https://arin-nya.tistory.com/)
- **Dataset**: [NamuWiki Anime RAG Dataset](https://huggingface.co/datasets/ArinNya/namuwiki_anime)
