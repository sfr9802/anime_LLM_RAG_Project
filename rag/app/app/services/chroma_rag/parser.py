from __future__ import annotations

import json
import logging
import os
import re
from typing import Literal, Tuple

from .utils import _env_float, _env_int

Mode = Literal["regex", "llm"]


class QueryParser:
    def __init__(self, chat, logger: logging.Logger | None = None) -> None:
        self._chat = chat
        self._log = logger or logging.getLogger("rag.query_parse")

    def _mode_from_env(self) -> Mode:
        mode = (os.getenv("RAG_QUERY_PARSER", "regex") or "regex").strip().lower()
        return "llm" if mode == "llm" else "regex"

    def parse_regex(self, q: str) -> str:
        # "파싱"이라기보다 최소한의 클린징/정규화
        cleaned = re.sub(r"[\"'`]+", "", q or "")
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or (q or "")

    async def parse_llm(self, q: str) -> str:
        from ...prompt.loader import render_template

        prompt = render_template("query_parse_prompt", user_query=q)
        max_tokens = _env_int("RAG_QUERY_PARSE_MAX_TOKENS", 120)
        temperature = _env_float("RAG_QUERY_PARSE_TEMPERATURE", 0.0)

        try:
            out = await self._chat(
                [{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception:
            self._log.exception("Query parse failed; falling back to original query.")
            return q

        raw = (out or "").strip()
        if not raw:
            self._log.info("Query parse returned empty output; falling back.")
            return q

        # JSON 안전 파싱
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            left = raw.find("{")
            right = raw.rfind("}")
            if left < 0 or right < 0 or right <= left:
                self._log.info("Query parse returned non-JSON output; falling back.")
                return q
            try:
                data = json.loads(raw[left : right + 1])
            except json.JSONDecodeError:
                self._log.info("Query parse returned invalid JSON; falling back.")
                return q

        parsed = (data.get("query") or "").strip()
        if parsed:
            self._log.info("Query parsed: original=%s parsed=%s", q, parsed)
            return parsed

        self._log.info("Query parse produced empty query; falling back.")
        return q

    async def parse(self, q: str, *, force_mode: Mode | None = None) -> Tuple[str, Mode]:
        """
        Returns (parsed_query, mode_used).
        mode can be forced for debug/retrieval-only endpoints.
        """
        mode: Mode = force_mode or self._mode_from_env()
        if mode == "llm":
            return await self.parse_llm(q), "llm"
        return self.parse_regex(q), "regex"


__all__ = ["QueryParser"]
