from typing import Optional
from services.search_service import SearchService

class RagService:
    def __init__(self, search: SearchService):
        self.search = search

    def retrieve_docs(self, question: str, section: Optional[str] = None, top_k: int = 6):
        return self.search.search(question, section=section, top_k=top_k)

    def build_context(self, docs, max_chars: int = 3000) -> str:
        # 간단 컨텍스트 빌더 (필요하면 문서간 구분자/메타 포함)
        parts, size = [], 0
        for d in docs:
            chunk = d.text.strip()
            if not chunk:
                continue
            if size + len(chunk) > max_chars:
                break
            parts.append(chunk)
            size += len(chunk)
        return "\n\n".join(parts)

    # 나중에 LLM 붙일 메서드
    # def answer(self, question: str, docs):
    #     context = self.build_context(docs)
    #     prompt = render_template("rag_prompt", context=context, question=question)
    #     return ask_gpt(prompt)
