
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

<<<<<<< Updated upstream
**품질 지표 2025-09-09 기준**:  
- recall@5 **0.3**  
- p95 **50ms**  
- dup_rate **0.07**
=======
> FastAPI 기반 모듈화된 RAG 백엔드. 검색/재랭킹/응답 생성을 모두 지원.
>>>>>>> Stashed changes

- `/ingest`: 문서 업서트 (Mongo + Chroma)
- `/retrieve`: 임베딩 검색 + (선택) MMR
- `/answer`: 검색 기반 LLM 응답 생성
- `/debug/bench`: 품질 벤치마크용 API (recall, dup_rate, p95)

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

🖼️ 시퀀스 다이어그램

#### 🔐 로그인 흐름 (OAuth2 → JWT → OTC 발급)

![로그인](./로그인.png)

#### 🔁 API 요청 흐름 (프록시 + Redis 블랙리스트 검증)

![리버스프록시](./리버스프록시.png)

#### 🚪 로그아웃 흐름 (Redis 블랙리스트 + Refresh 삭제)

![로그아웃](./로그아웃.png)

---

## ⚙️ Tech Highlights

- 💡 **MMR Re-ranking**: Semantic 다양성 보장, 중복 제거
- ✂️ **Chunking Strategy**: 한국어 종결어미/제목 기반 청킹
- 🧪 **Benchmark APIs**: recall@k, dup_rate, p95 등 측정 가능
- 🔗 **Postman/Bruno Collections**: 테스트 자동화 지원
- 🔁 **Embeddings**: SBERT, bge-m3, Instruct 등 비교 실험

---

## 🔭 Roadmap

- [ ] bge-m3 → instruct 모델 전환 A/B 테스트
- [ ] Chroma efSearch 최적곡선 정리
- [ ] p95 줄이기 위한 캐시 전략 실험
- [ ] 대시보드 시각화 페이지 연동

---

## 📎 Links

- **Blog**: [기술 아키텍처 및 구현 기록](https://arin-nya.tistory.com/)
- **Dataset**: [NamuWiki Anime RAG Dataset](https://huggingface.co/datasets/ArinNya/namuwiki_anime)
- **Collections**: `collections/rag-demo.json`
