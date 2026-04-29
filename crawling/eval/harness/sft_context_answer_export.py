"""Phase 4 — SFT exporter: context+answer.

For each suitable chunk, builds a record where the user message bundles
the chunk_text as context plus a section_type-derived question, and the
assistant message returns a verbatim ``evidence_span`` from chunk_text.

Phase 4 spec §5: the assistant answer must NOT bring in knowledge from
outside the context. Without an LLM we cannot paraphrase faithfully, so
``answer == evidence_span`` (a true substring of chunk_text). Short
literal answers beat hallucinated ones.

Quality gating mirrors Phase 4 spec §8: ``is_stub`` and ``is_table_like``
chunks are skipped by default; ``is_list_like`` is intentionally NOT a
skip signal (character/episode/music lists are useful as evidence).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, Optional, Tuple

from .qa_candidate_extractor import (
    QUESTION_TEMPLATES_BY_SECTION,
    extract_qa_candidate,
    supported_section_types as _qa_supported_section_types,
)
from .sft_query_rewrite_export import DocMeta
from .sft_schema import (
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    SCHEMA_VERSION_SFT_CONTEXT_ANSWER,
    SFTMessage,
    SFTRecord,
    SFTSource,
)
from .split_manifest import SPLIT_NAMES, SplitManifest


SYSTEM_PROMPT_CONTEXT_ANSWER = (
    "주어진 문맥에 근거해서만 답변하라. "
    "문맥에 없으면 모른다고 답하라."
)

DEFAULT_MIN_CONTEXT_CHARS = 60


# Soft "skip reason" enum surfaced to callers so the CLI can attribute
# every drop to one of the Phase 4 spec §9 categories.
SKIP_REASONS: Tuple[str, ...] = (
    "low_quality",
    "too_short",
    "missing_manifest",
    "missing_evidence",
    "unsupported_section_type",
)


def supported_section_types() -> Tuple[str, ...]:
    return _qa_supported_section_types()


def is_low_quality_metadata(
    metadata: Optional[Dict[str, Any]],
    *,
    min_chars: int,
) -> Tuple[bool, str]:
    """Classify a chunk's quality from its ``metadata`` block.

    Returns ``(is_low_quality, reason)`` where ``reason`` is one of
    :data:`SKIP_REASONS` (``""`` when ``is_low_quality=False``). Note
    that ``is_list_like`` is not a low-quality signal — anime list pages
    (캐스팅, OST 트랙, 방영 목록) carry useful retrieval signal.
    """
    if not isinstance(metadata, dict):
        return False, ""
    if bool(metadata.get("is_stub")):
        return True, "low_quality"
    if bool(metadata.get("is_table_like")):
        return True, "low_quality"
    text_length = metadata.get("text_length")
    if isinstance(text_length, (int, float)) and text_length < min_chars:
        return True, "too_short"
    return False, ""


def build_context_answer_record(
    chunk: Dict[str, Any],
    *,
    doc_meta: DocMeta,
    split: str,
    min_context_chars: int = DEFAULT_MIN_CONTEXT_CHARS,
) -> Optional[SFTRecord]:
    """Build a single context_answer SFTRecord from a chunk.

    Returns ``None`` when the chunk is unsuitable (no work_title,
    chunk_text shorter than ``min_context_chars``, unsupported
    section_type, or no extractable evidence span).
    """
    title = doc_meta.work_title
    if not isinstance(title, str) or not title.strip():
        return None
    chunk_text = chunk.get("chunk_text") or ""
    if not isinstance(chunk_text, str) or len(chunk_text) < min_context_chars:
        return None

    section_type = chunk.get("section_type", "other")
    qa = extract_qa_candidate(
        title=title,
        section_type=section_type,
        chunk_text=chunk_text,
        min_chars=min_context_chars,
    )
    if qa is None:
        return None
    if not qa.evidence_span or qa.evidence_span not in chunk_text:
        return None

    user_content = (
        f"[CONTEXT]\n{chunk_text}\n\n[QUESTION]\n{qa.question}"
    )
    return SFTRecord(
        schema_version=SCHEMA_VERSION_SFT_CONTEXT_ANSWER,
        messages=[
            SFTMessage(role=ROLE_SYSTEM, content=SYSTEM_PROMPT_CONTEXT_ANSWER),
            SFTMessage(role=ROLE_USER, content=user_content),
            SFTMessage(role=ROLE_ASSISTANT, content=qa.answer),
        ],
        source=SFTSource(
            doc_id=str(chunk.get("doc_id") or ""),
            section_id=str(chunk.get("section_id") or ""),
            section_key=str(chunk.get("section_key") or ""),
            chunk_id=str(chunk.get("chunk_id") or ""),
            split=split,
            evidence_span=qa.evidence_span,
        ),
    )


def iter_context_answer_records(
    chunks: Iterable[Dict[str, Any]],
    *,
    manifest: SplitManifest,
    doc_meta_lookup: Dict[str, DocMeta],
    min_context_chars: int = DEFAULT_MIN_CONTEXT_CHARS,
    include_low_quality: bool = False,
    allow_missing_docs: bool = False,
) -> Iterator[Tuple[str, SFTRecord]]:
    """Yield ``(split, record)`` pairs. Quality gating is built in.

    Routing is doc_id-based; a chunk's split is determined entirely by
    the manifest, so a chunk's context never crosses split boundaries.
    """
    doc_to_split: Dict[str, str] = {
        d: s for s in SPLIT_NAMES for d in manifest.doc_ids.get(s, [])
    }
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
        if not include_low_quality:
            low, _ = is_low_quality_metadata(
                chunk.get("metadata"), min_chars=min_context_chars
            )
            if low:
                continue
        meta = doc_meta_lookup.get(doc_id)
        if meta is None:
            continue
        record = build_context_answer_record(
            chunk,
            doc_meta=meta,
            split=split,
            min_context_chars=min_context_chars,
        )
        if record is None:
            continue
        yield split, record
