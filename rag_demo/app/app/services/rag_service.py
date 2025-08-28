# app/app/services/rag_service.py
from __future__ import annotations
from typing import Any, Dict, List, Optional
import numpy as np

from app.app.infra.vector.chroma_store import search as chroma_search
from app.app.services.adapters import flatten_chroma_result
from app.app.domain.embeddings import embed_queries, embed_passages
from app.app.infra.llm.provider import get_chat
from app.app.configure import config

# 모델/유틸 경로가 환경마다 다를 수 있어 안전하게 임포트
try:
    from app.app.domain.models.document_model import DocumentItem
    from app.app.domain.models.query_model import RAGQueryResponse
    from app.app.infra.vector.metrics import to_similarity
except Exception:
    try:
        from app.app.models.document_model import DocumentItem
        from app.app.models.query_model import RAGQueryResponse
        from app.app.vector_store.metrics import to_similarity
    except Exception:
        # 사용자가 rag_demo 네임스페이스를 쓴 경우
        from rag_demo.app.app.domain.models.document_model import DocumentItem
        from rag_demo.app.app.domain.models.query_model import RAGQueryResponse
        from rag_demo.app.app.infra.vector.metrics import to_similarity


class RagService:
    def __init__(self):
        self.chat = get_chat()
        self._last_space: str = "cosine"  # 최근 검색 벡터 공간 저장(점수 변환에 필요)

    def _mmr(self, q: str, items: List[Dict[str, Any]], k: int, lam: float = 0.5) -> List[Dict[str, Any]]:
        if not items:
            return items
        texts = [(it.get("text") or "") for it in items]
        cvs = np.array(embed_passages(texts))     # (n,d)
        qv = np.array(embed_queries([q]))[0]      # (d,)
        n = cvs.shape[0]
        if n <= k:
            return items

        # cosine
        def cos(a, b):
            denom = (np.linalg.norm(a) + 1e-8) * (np.linalg.norm(b, axis=1) + 1e-8)
            return (b @ a) / denom

        sim_q = cos(qv, cvs)
        selected: List[int] = []
        remaining = set(range(n))
        while len(selected) < k and remaining:
            if not selected:
                i = int(np.argmax(sim_q))
                selected.append(i); remaining.remove(i)
            else:
                sel = cvs[np.array(selected)]
                sim_div = np.max((cvs @ sel.T) /
                                 ((np.linalg.norm(cvs, axis=1, keepdims=True) + 1e-8) *
                                  (np.linalg.norm(sel, axis=1) + 1e-8)), axis=1)
                mmr = lam * sim_q - (1 - lam) * sim_div
                mmr[np.array(selected)] = -1e9
                i = int(np.argmax(mmr))
                selected.append(i); remaining.discard(i)
        return [items[i] for i in selected]

    def retrieve_docs(
        self,
        q: str,
        *,
        k: int = 6,
        where: Optional[Dict[str, Any]] = None,
        candidate_k: Optional[int] = None,
        use_mmr: bool = True,
        lam: float = 0.5,
    ) -> List[Dict[str, Any]]:
        cand = max(k, candidate_k or max(k * 5, 40)) if use_mmr else k
        res = chroma_search(
            query=q, n=cand, where=where,
            include_docs=True, include_metas=True, include_ids=True, include_distances=True
        )
        # 벡터 공간 기억(코사인/IP/L2 등에 따라 score 변환이 달라짐)
        self._last_space = (res.get("space") or "cosine").lower()

        items = flatten_chroma_result(res)  # {id, text, distance, score, metadata{...}}

        # 문서 중복 제거(같은 doc_id/제목·섹션 조합은 하나만)
        seen = set()
        dedup: List[Dict[str, Any]] = []
        for it in items:
            meta = it.get("metadata") or {}
            key = meta.get("doc_id") or (meta.get("title"), meta.get("section")) or it.get("id")
            if key in seen:
                continue
            seen.add(key)
            dedup.append(it)

        # score 없으면 여기서 미리 채워두기(0..1로 정규화)
        for it in dedup:
            if it.get("score") is None:
                it["score"] = to_similarity(it.get("distance"), space=self._last_space)

        if use_mmr:
            dedup = self._mmr(q, dedup, k=k, lam=lam)
        else:
            # 기본 정렬: score desc → distance asc
            dedup.sort(key=lambda x: (-(x.get("score") or -1.0), (x.get("distance") or 1e9)))
            dedup = dedup[:k]

        return dedup[:k]

    def build_context(self, docs: List[Dict[str, Any]], *, per_doc_limit: int = 1200, hard_limit: int = 6000) -> str:
        chunks: List[str] = []
        total = 0
        for i, d in enumerate(docs, 1):
            meta = d.get("metadata") or {}
            title = meta.get("seed_title") or meta.get("parent") or meta.get("title") or ""
            section = meta.get("section") or ""
            body = (d.get("text") or "").strip()
            if not body:
                continue
            if per_doc_limit and len(body) > per_doc_limit:
                body = body[:per_doc_limit]
            piece = f"[S{i}] {title} · {section}\n{body}"
            if hard_limit and total + len(piece) > hard_limit:
                break
            chunks.append(piece)
            total += len(piece)
        return "\n\n".join(chunks)

    def _render_prompt(self, question: str, context: str) -> str:
        return (
            "아래 <컨텍스트>만 근거로 한국어로 간결하게 답해. "
            "컨텍스트에 없는 것은 모른다고 답해. 허구 금지.\n\n"
            f"<컨텍스트>\n{context}\n\n"
            f"<질문>\n{question}\n"
        )

    async def ask(
        self,
        q: str,
        *,
        k: int = 6,
        where: Optional[Dict[str, Any]] = None,
        candidate_k: Optional[int] = None,
        use_mmr: bool = True,
        lam: float = 0.5,
        max_tokens: int = 512,
        temperature: float = 0.2,
        preview_chars: int = 600,
    ) -> Dict[str, Any]:
        # 1) 문서 검색
        docs = self.retrieve_docs(
            q, k=k, where=where, candidate_k=candidate_k, use_mmr=use_mmr, lam=lam
        )
        context = self.build_context(docs)
        if not context:
            return RAGQueryResponse(
                question=q, answer="관련 컨텍스트가 없습니다.", documents=[]
            ).model_dump()

        # 2) 프롬프트 구성 & 호출
        prompt = self._render_prompt(q, context)
        messages = [
            {"role": "system", "content": "답변은 한국어. 제공된 컨텍스트만 사용. 모르면 모른다고 답하라."},
            {"role": "user", "content": prompt},
        ]
        try:
            out = await self.chat(messages, max_tokens=max_tokens, temperature=temperature)
        except Exception as e:
            # 호출 실패는 1차적으로 메시지로 전달(라우터에서 HTTPException으로 매핑 권장)
            return RAGQueryResponse(
                question=q, answer=f"LLM 호출 실패: {e}", documents=[]
            ).model_dump()

        # 3) 문서들을 DocumentItem으로 스키마 맞춰 변환
        items: List[DocumentItem] = []
        space = self._last_space  # retrieve_docs에서 기록한 벡터 공간 사용
        for d in docs:
            meta = d.get("metadata") or {}
            text = (d.get("text") or "").strip()
            if not text:
                continue  # DocumentItem.text는 공백 불가
            score = d.get("score")
            if score is None:
                score = to_similarity(d.get("distance"), space=space)

            items.append(
                DocumentItem(
                    id=str(d.get("id") or ""),
                    page_id=meta.get("page_id"),
                    chunk_id=meta.get("chunk_id"),
                    url=meta.get("url"),
                    title=meta.get("title"),
                    section=meta.get("section"),
                    seed=meta.get("seed_title") or meta.get("parent") or meta.get("title"),
                    score=float(score) if score is not None else None,
                    text=text[:1200],  # build_context의 per_doc_limit와 맞춤
                )
            )

        # 4) 스키마 응답
        return RAGQueryResponse(question=q, answer=out, documents=items).model_dump()
