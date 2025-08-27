# services/rag_service.py
from __future__ import annotations
from typing import Optional, Dict, Any, List
from pathlib import Path
from jinja2 import Template

from ..services.search_service import SearchService
from ..configure import config
# from infra.llm.local_llm_client import chat  # ← 로컬 LLM HTTP(or in-process) 클라
from ..infra.llm.clients.local_http_client import chat
class RagService:
    def __init__(self, search: SearchService):
        self.search = search
        self.max_chars = 3000

    def retrieve_docs(self, question: str, section: Optional[str] = None, top_k: Optional[int] = None):
        k = top_k or config.TOP_K
        return self.search.search(question, section=section, top_k=k)

    def build_context(self, docs, max_chars: Optional[int] = None) -> str:
        max_chars = max_chars or self.max_chars
        parts, size = [], 0
        seen_titles = set()
        for d in docs:
            title = getattr(d, "title", None) if not isinstance(d, dict) else (d.get("title"))
            if title:
                if title in seen_titles:
                    continue
                seen_titles.add(title)
            text = getattr(d, "text", None) if not isinstance(d, dict) else d.get("text")
            if not text: continue
            t = text.strip()
            if not t: continue
            if size + len(t) > max_chars: break
            parts.append(t); size += len(t)
        return "\n\n".join(parts)

    def _render_prompt(self, question: str, context: str) -> str:
        # 우선 네가 가진 렌더러가 있으면 사용
        try:
            from prompt.renderer import render_template as _render
            # 템플릿 파일명이 rag_prompt.j2라 가정 (네 구조에 맞춤)
            return _render("rag_prompt.j2", question=question, context=context)
        except Exception:
            # fallback: 직접 템플릿 읽기
            tpl_path = Path(__file__).resolve().parents[1] / "prompt" / "templates" / "rag_prompt.j2"
            if tpl_path.exists():
                tpl = Template(tpl_path.read_text(encoding="utf-8"))
                return tpl.render(question=question, context=context)
            # 최후의 보루(임시 프롬프트)
            return (
                "You are a precise assistant. Use ONLY the provided context to answer.\n"
                "If not in context, reply briefly that you don't know.\n\n"
                f"Question:\n{question}\n\nContext:\n{context}\n\nAnswer:"
            )

    async def answer(
        self,
        question: str,
        section: Optional[str] = None,
        top_k: Optional[int] = None,
        max_tokens: int = 512,
        temperature: float = 0.2,
    ) -> Dict[str, Any]:
        docs = self.retrieve_docs(question, section=section, top_k=top_k or config.TOP_K)
        context = self.build_context(docs)
        if not context:
            return {
                "answer": "컨텍스트가 없어 답변을 생성하지 않는다.",
                "sources": [],
                "used_model": config.LLM_MODEL,
            }

        prompt = self._render_prompt(question, context)
        messages = [
            {"role": "system", "content": "답변은 한국어. 제공된 컨텍스트만 사용. 모르면 모른다고 답하라."},
            {"role": "user", "content": prompt},
        ]
        out = await chat(messages, model=config.LLM_MODEL, max_tokens=max_tokens, temperature=temperature)

        # 소스 메타 간단 정리
        sources: List[Dict[str, Any]] = []
        for d in docs:
            meta = {}
            for k in ("id", "doc_id", "title", "score", "seg_index"):
                v = getattr(d, k, None) if not isinstance(d, dict) else d.get(k)
                if v is not None:
                    meta[k] = v
            if meta:
                sources.append(meta)

        return {"answer": out, "sources": sources, "used_model": config.LLM_MODEL}
