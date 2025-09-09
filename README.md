# 🗂️ Backend Portfolio — RAG · Data Pipeline · Security

**전문 분야**: 도메인 특화 RAG 백엔드 & 데이터 파이프라인  
**주요 스택**: FastAPI · Python · Chroma(HNSW) · MongoDB · Spring Security(OAuth2/JWT)  

---

## 📌 Top Projects

### 1) RAG Backend (2025)
**역할**: 아키텍처 설계 · 임베딩/인덱싱/검색 통합 · 디버그/벤치 하네스 구축  
**핵심 기능**:  
- `/ingest` : 문서·메타데이터 업서트  
- `/retrieve` : 쿼리 → top-k 검색 + (선택) MMR 재랭킹  
- `/answer` : 검색 결과 기반 응답 생성  
- `/debug/bench` : recall@k, dup_rate, p95(ms) 벤치마크

**품질 지표 2025-09-09 기준**:  
- recall@5 **0.3**  
- p95 **50ms**  
- dup_rate **0.07**

**데모**: Swagger 캡처 · Bruno/Postman 컬렉션(`collections/rag-demo.json`)  

**API 예시(구현중)**:
```http
POST /retrieve
{
  "query": "작품 A 등장인물",
  "k": 5,
  "use_mmr": true,
  "lambda_": 0.3
}

200 OK
{
  "data": {
    "hits": [
      {"id": "doc_123", "score": 0.84},
      ...
    ]
  },
  "meta": { "k": 5, "mmr": true, "lambda": 0.3 },
  "error": null
}
```

---

### 2) NamuWiki Crawler & Cleaning (2025)
**역할**: 대규모 재귀 크롤링 설계 · 데이터 정제 및 노이즈 제거 · 스토리지 설계  
**기술**: Selenium · BeautifulSoup · 정규식 · 멀티프로세싱  
**규모**: 문서 **~7,700**개 수집, JSONL 포맷으로 정제 후 Mongo/MySQL 저장  
**결과물**: HuggingFace 업로드 가능한 RAG용 데이터셋  
**특징**:  
- 등장인물/설정 등 하위 링크 재귀 수집  
- 라이선스·푸터·광고 제거 규칙 적용  
- 청킹(Chunking) 사전 처리

---

### 3) Spring Security / OAuth2 JWT Middleware
**역할**: 인증·인가 미들웨어 설계 및 구현  
**기능**:  
- OAuth2 팝업 로그인 (Google) → JWT 발급/저장  
- Redis 기반 Refresh Token 및 블랙리스트 로그아웃  
- JWT 인증 필터와 SecurityContext 관리 분리  
**성과**: REST API용 Stateless 인증 환경 구축  
**프론트 연계**: React 기반 토큰 처리 및 axios 헤더 자동화

---

## 🛠️ Bench & Debug
_아직 구현 전_

---

## 🚀 Tech Highlights
- **MMR 재랭킹**: 다양성 향상, 중복률 감소  
- **한국어 청킹 규칙**: 종결어미·제목 경계 보정, avg_len≈350  
- **운영 편의성**: Swagger 활성화, Bruno/Postman 컬렉션 제공  
- **데이터 파이프라인**: 수집 → 정제 → 벡터화 → 검색까지 일관된 흐름

---

## 📅 Roadmap
- [ ] 임베딩 모델 교체(bge-m3 → instruct) A/B 테스트  
- [ ] efSearch 튜닝 곡선 정리  
- [ ] 캐싱/프리히트로 p95 절감 실험  
- [ ] RAG 품질 지표 시각화 페이지 추가

---

## 📎 Links
- **Blog**: [기술 아키텍처 및 구현 기록](https://arin-nya.tistory.com/)  
- **HuggingFace Dataset**: [NamuWiki Anime RAG Dataset](https://huggingface.co/datasets/ArinNya/namuwiki_anime)  
- **Bruno/Postman Collection**: `collections/rag-demo.json`
