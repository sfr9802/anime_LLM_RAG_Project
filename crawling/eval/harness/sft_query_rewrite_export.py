"""Phase 4 — SFT exporter: query rewrite.

Generates messages-format SFT records that train a model to translate a
free-form Korean wiki question into a search-friendly JSON envelope::

    {"normalized_query": "...", "entities": [...], "filters": {...}}

Phase 4 is rule-based on purpose (spec §1, §4): the goal is to validate
the SFT generation pipeline, not to maximise query-rewrite quality.

A single chunk produces at most one record. Multiple chunks of the same
``(doc_id, section_type)`` produce identical user queries — the
exporter therefore deduplicates on ``user_query`` per split (a small
LRU set). The first chunk that yields a query wins; later identical
queries are dropped silently rather than tallied as a skip, since the
record they would have produced is already in the dataset.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .sft_schema import (
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    SCHEMA_VERSION_SFT_QUERY_REWRITE,
    SFTMessage,
    SFTRecord,
    SFTSource,
)
from .split_manifest import SPLIT_NAMES, SplitManifest


SYSTEM_PROMPT_QUERY_REWRITE = (
    "너는 애니메이션 문서 검색 시스템의 쿼리 정규화기다. "
    "사용자 질문을 검색 친화적인 JSON으로 변환하라."
)

# section_type -> templated user query. Match Phase 4 spec §4 verbatim.
USER_QUERY_TEMPLATES: Dict[str, str] = {
    "summary": "{title} 개요 알려줘",
    "synopsis": "{title} 줄거리 알려줘",
    "character": "{title} 등장인물 알려줘",
    "setting": "{title} 설정 알려줘",
    "worldview": "{title} 세계관 알려줘",
    "concept": "{title} 개념 설명해줘",
    "episode": "{title} 에피소드 알려줘",
    "evaluation": "{title} 평가 어때?",
    "production": "{title} 제작 정보 알려줘",
    "music": "{title} 음악 알려줘",
    "trivia": "{title} 여담 알려줘",
}

# section_type -> Korean keyword used in the assistant's normalized_query.
_NORMALIZED_KEYWORDS: Dict[str, str] = {
    "summary": "개요",
    "synopsis": "줄거리",
    "character": "등장인물",
    "setting": "설정",
    "worldview": "세계관",
    "concept": "개념",
    "episode": "에피소드",
    "evaluation": "평가",
    "production": "제작",
    "music": "음악",
    "trivia": "여담",
}

# section_type -> retrieval filter. Sets cluster cousin types together
# (worldview/concept under setting, etc.) so retrieval can fan out to
# semantically adjacent sections. Order is preserved for determinism.
SECTION_TYPE_FILTERS: Dict[str, List[str]] = {
    "summary": ["summary"],
    "synopsis": ["synopsis", "summary"],
    "character": ["character"],
    "setting": ["setting", "worldview", "concept"],
    "worldview": ["setting", "worldview", "concept"],
    "concept": ["setting", "worldview", "concept"],
    "episode": ["episode"],
    "evaluation": ["evaluation"],
    "production": ["production"],
    "music": ["music"],
    "trivia": ["trivia"],
}


def supported_section_types() -> Tuple[str, ...]:
    return tuple(USER_QUERY_TEMPLATES.keys())


@dataclass
class DocMeta:
    """Per-document metadata pulled from pages_v4 — not on the chunk."""

    work_title: str
    page_title: str
    aliases: List[str]


def build_doc_meta_lookup(pages: Iterable[Dict[str, Any]]) -> Dict[str, DocMeta]:
    """Index ``page_id -> DocMeta`` from a v4 pages iterable.

    ``work_title`` is preferred when present (since it's the canonical
    work-level name); ``page_title`` is the fallback for the rare page
    that lost its work_title during conversion.
    """
    lookup: Dict[str, DocMeta] = {}
    for p in pages:
        if not isinstance(p, dict):
            continue
        pid = p.get("page_id")
        if not isinstance(pid, str) or not pid.strip():
            continue
        page_title = p.get("page_title") or ""
        if not isinstance(page_title, str):
            page_title = ""
        page_title = page_title.strip()
        work_title_raw = p.get("work_title")
        if isinstance(work_title_raw, str) and work_title_raw.strip():
            work_title = work_title_raw.strip()
        else:
            work_title = page_title
        raw_aliases = p.get("aliases") or []
        aliases: List[str] = []
        if isinstance(raw_aliases, list):
            for a in raw_aliases:
                if isinstance(a, str) and a.strip():
                    aliases.append(a.strip())
        lookup[pid.strip()] = DocMeta(
            work_title=work_title,
            page_title=page_title,
            aliases=aliases,
        )
    return lookup


def build_query_rewrite_record(
    chunk: Dict[str, Any],
    *,
    doc_meta: DocMeta,
    split: str,
) -> Optional[SFTRecord]:
    """Build a single query_rewrite SFTRecord from a chunk.

    Returns ``None`` when the chunk's section_type is not supported or
    required metadata is missing. The caller is responsible for
    ``user_query`` dedup (the same templated query is produced by every
    chunk under the same ``(work_title, section_type)``).
    """
    section_type = chunk.get("section_type")
    if not isinstance(section_type, str) or section_type not in USER_QUERY_TEMPLATES:
        return None
    title = doc_meta.work_title
    if not isinstance(title, str) or not title.strip():
        return None
    title = title.strip()

    user_query = USER_QUERY_TEMPLATES[section_type].format(title=title)
    keyword = _NORMALIZED_KEYWORDS[section_type]
    normalized_query = f"{title} {keyword}".strip()

    entities: List[str] = [title]
    for a in doc_meta.aliases:
        if a and a != title and a not in entities:
            entities.append(a)

    payload = {
        "normalized_query": normalized_query,
        "entities": entities,
        "filters": {
            "title": title,
            "section_type": list(SECTION_TYPE_FILTERS[section_type]),
        },
    }
    assistant_content = json.dumps(payload, ensure_ascii=False)

    return SFTRecord(
        schema_version=SCHEMA_VERSION_SFT_QUERY_REWRITE,
        messages=[
            SFTMessage(role=ROLE_SYSTEM, content=SYSTEM_PROMPT_QUERY_REWRITE),
            SFTMessage(role=ROLE_USER, content=user_query),
            SFTMessage(role=ROLE_ASSISTANT, content=assistant_content),
        ],
        source=SFTSource(
            doc_id=str(chunk.get("doc_id") or ""),
            section_id=str(chunk.get("section_id") or ""),
            section_key=str(chunk.get("section_key") or ""),
            chunk_id=str(chunk.get("chunk_id") or ""),
            split=split,
        ),
    )


def iter_query_rewrite_records(
    chunks: Iterable[Dict[str, Any]],
    *,
    manifest: SplitManifest,
    doc_meta_lookup: Dict[str, DocMeta],
    allow_missing_docs: bool = False,
) -> Iterator[Tuple[str, SFTRecord]]:
    """Yield ``(split, record)`` pairs for chunks routed via the manifest.

    Per-split ``user_query`` dedup is handled inside the iterator so
    callers can stream straight to per-split files without re-walking
    chunks.
    """
    doc_to_split: Dict[str, str] = {
        d: s for s in SPLIT_NAMES for d in manifest.doc_ids.get(s, [])
    }
    seen_queries: Dict[str, set] = {s: set() for s in SPLIT_NAMES}

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        doc_id = chunk.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id.strip():
            continue
        doc_id = doc_id.strip()
        split = doc_to_split.get(doc_id)
        if split is None:
            if allow_missing_docs:
                continue
            raise ValueError(
                f"chunk doc_id {doc_id!r} not in manifest "
                f"(use allow_missing_docs=True to skip)"
            )
        meta = doc_meta_lookup.get(doc_id)
        if meta is None:
            continue
        record = build_query_rewrite_record(chunk, doc_meta=meta, split=split)
        if record is None:
            continue
        user_query = record.messages[1].content
        if user_query in seen_queries[split]:
            continue
        seen_queries[split].add(user_query)
        yield split, record
