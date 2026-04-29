"""Export RAG chunks (RagChunkV4) from a v4 pages JSONL.

The function ``export_rag_chunks`` is a pure generator that walks a
sequence of v4 page dicts, splits each section's clean_text into chunk
candidates, filters low-quality sections by default, and yields fully-
populated :class:`RagChunkV4` records.

The chunk text splitting reuses ``namu_v3_to_v4._split_paragraphs`` so that
v3->v4 chunks and freshly-exported RAG chunks group sentences the same
way. Importing a private helper from a sibling module is a deliberate
trade — the alternative is duplicating the splitter, which would drift.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

from .dataset_v4_schema import normalize_text_for_id
from .namu_v3_to_v4 import _split_paragraphs as split_paragraphs  # noqa: F401  (cross-module reuse)
from .rag_chunk_schema import (
    EMBEDDING_TEXT_VARIANTS,
    RagChunkMetadata,
    RagChunkV4,
    build_rag_embedding_text,
    make_chunk_id,
)


# Defaults. The CLI surfaces these as flags.
DEFAULT_MIN_CHARS = 60  # matches Phase 1 STUB_THRESHOLD
DEFAULT_EMBEDDING_TEXT_VARIANT = "title_section"


def _section_chunk_source(section: Dict[str, Any]) -> str:
    """Pick the section's text source for chunking.

    Priority: ``clean_text`` > ``text`` > ``raw_text``. ``raw_text`` is the
    final fallback so we never lose information for sections that only
    carried legacy/unprocessed text.
    """
    for key in ("clean_text", "text", "raw_text"):
        v = section.get(key)
        if isinstance(v, str) and v.strip():
            return v
    return ""


def _section_first_link(section: Dict[str, Any]) -> Optional[str]:
    links = section.get("links") or []
    if isinstance(links, list):
        for u in links:
            if isinstance(u, str) and u:
                return u
    return None


def _is_low_quality(section: Dict[str, Any], min_chars: int) -> bool:
    """Default exclusion rules for low-quality sections.

    By spec: drop ``is_stub`` or ``is_table_like`` sections, and drop
    sections whose clean_text length is below ``min_chars``. ``is_list_like``
    is intentionally NOT a drop signal — list sections in anime docs
    (방영 목록, 등장인물 목록, OST 트랙) are useful for retrieval.
    """
    quality = section.get("quality") or {}
    if isinstance(quality, dict):
        if bool(quality.get("is_stub")):
            return True
        if bool(quality.get("is_table_like")):
            return True
        text_length = quality.get("text_length")
        if isinstance(text_length, int) and text_length < min_chars:
            return True
    return False


def export_rag_chunks(
    pages: Iterable[Dict[str, Any]],
    *,
    embedding_text_variant: str = DEFAULT_EMBEDDING_TEXT_VARIANT,
    min_chars: int = DEFAULT_MIN_CHARS,
    include_low_quality: bool = False,
) -> Iterator[RagChunkV4]:
    """Yield :class:`RagChunkV4` records for every emitted chunk.

    Parameters
    ----------
    pages
        Iterable of page dicts in the v4 page schema (e.g. parsed from
        ``pages_v4.jsonl``). Pages without ``page_id`` or ``page_title``
        are skipped silently.
    embedding_text_variant
        One of ``raw / title / title_section / title_section_alias``.
    min_chars
        Minimum chunk_text length (also used as the section drop
        threshold). Default matches Phase 1's STUB_THRESHOLD so chunks
        below the section stub limit are filtered consistently.
    include_low_quality
        When ``True``, do not apply the low-quality section / min_chars
        filters. Useful for diagnostics / coverage runs.
    """
    if embedding_text_variant not in EMBEDDING_TEXT_VARIANTS:
        raise ValueError(
            f"unknown embedding_text variant: {embedding_text_variant!r}; "
            f"expected one of {EMBEDDING_TEXT_VARIANTS}"
        )

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = page.get("page_id") or ""
        page_title = page.get("page_title") or ""
        if not page_id or not page_title:
            continue
        aliases = page.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        canonical_url = page.get("canonical_url") if isinstance(page.get("canonical_url"), str) else None
        sections = page.get("sections") or []
        if not isinstance(sections, list):
            continue

        for sec in sections:
            if not isinstance(sec, dict):
                continue

            if not include_low_quality and _is_low_quality(sec, min_chars):
                continue

            chunk_source = _section_chunk_source(sec)
            if not chunk_source.strip():
                continue

            section_id = sec.get("section_id") or ""
            # section_key is the Phase 1 stable key; fall back to section_id
            # if a producer (e.g. an old converter) didn't populate it yet.
            section_key = sec.get("section_key") or section_id
            if not section_key:
                # without any section identifier we cannot build a stable
                # chunk_id — skip rather than collapse to page-level ID.
                continue
            section_path = sec.get("heading_path") or []
            if not isinstance(section_path, list):
                section_path = []
            section_type = sec.get("section_type") or "other"
            section_url = _section_first_link(sec) or canonical_url

            quality = sec.get("quality") or {}
            if not isinstance(quality, dict):
                quality = {}

            # Re-split clean_text into chunk candidates. _split_paragraphs
            # already groups long paragraphs to ~800 chars and hard-splits
            # tabular dumps with no sentence terminators.
            candidates = split_paragraphs(chunk_source) or [chunk_source]

            # Per-section occurrence counter so two chunks with the exact
            # same normalised text get different chunk_ids deterministically.
            text_seen: Counter = Counter()

            for cand in candidates:
                chunk_text = (cand or "").strip()
                if not chunk_text:
                    continue
                if not include_low_quality and len(chunk_text) < min_chars:
                    continue

                norm_text = normalize_text_for_id(chunk_text)
                occurrence = text_seen[norm_text]
                text_seen[norm_text] += 1

                chunk_id = make_chunk_id(
                    page_id=page_id,
                    section_key=section_key,
                    chunk_text=chunk_text,
                    occurrence=occurrence,
                )
                embedding_text = build_rag_embedding_text(
                    variant=embedding_text_variant,
                    title=page_title,
                    aliases=aliases,
                    section_path=section_path,
                    section_type=section_type,
                    chunk_text=chunk_text,
                )
                metadata = RagChunkMetadata(
                    source_url=section_url,
                    crawl_version="v4",
                    has_spoiler=bool(quality.get("has_spoiler", False)),
                    text_length=len(chunk_text),
                    noise_score=float(quality.get("noise_score") or 0.0),
                    is_stub=bool(quality.get("is_stub", False)),
                    is_table_like=bool(quality.get("is_table_like", False)),
                    is_list_like=bool(quality.get("is_list_like", False)),
                )
                yield RagChunkV4(
                    chunk_id=chunk_id,
                    doc_id=page_id,
                    title=page_title,
                    aliases=list(aliases),
                    section_id=section_id,
                    section_key=section_key,
                    section_path=list(section_path),
                    section_type=section_type,
                    chunk_text=chunk_text,
                    embedding_text=embedding_text,
                    metadata=metadata,
                )


# ---------------------------------------------------------------- file helpers


def iter_pages_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    """Yield parsed page dicts from a JSONL file. Skips empty / unparseable lines."""
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def write_chunks_jsonl(chunks: Iterable[RagChunkV4], path: Path) -> int:
    """Write an iterable of :class:`RagChunkV4` to a JSONL file. Returns row count."""
    path.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            obj = c.to_dict() if hasattr(c, "to_dict") else c
            f.write(json.dumps(obj, ensure_ascii=False))
            f.write("\n")
            n += 1
    return n


def export_jsonl(
    input_path: Path,
    output_path: Path,
    *,
    embedding_text_variant: str = DEFAULT_EMBEDDING_TEXT_VARIANT,
    min_chars: int = DEFAULT_MIN_CHARS,
    include_low_quality: bool = False,
) -> int:
    """Convenience wrapper used by the CLI: read pages JSONL, write chunks JSONL.
    Returns the number of chunks written.
    """
    pages = iter_pages_jsonl(input_path)
    chunks = export_rag_chunks(
        pages,
        embedding_text_variant=embedding_text_variant,
        min_chars=min_chars,
        include_low_quality=include_low_quality,
    )
    return write_chunks_jsonl(chunks, output_path)
