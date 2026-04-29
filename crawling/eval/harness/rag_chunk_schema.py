"""Schema + builders for the Phase 2 RAG chunk export.

This module is intentionally **separate** from ``dataset_v4_schema.ChunkV4``:
``ChunkV4`` is the canonical chunk produced by the v3->v4 converter and a
number of existing tests/pipelines depend on its exact field layout. The
RAG export is a downstream projection — it renames fields (``page_id`` ->
``doc_id``, ``page_title`` -> ``title``, ``text`` -> ``chunk_text``,
``text_for_embedding`` -> ``embedding_text``), nests quality flags into a
``metadata`` block, and stabilises ``chunk_id`` against section reordering
by hashing on ``section_key`` (Phase 1) instead of ``section_id``.

Keeping the projection in its own dataclass means we can iterate the RAG
schema without touching the pages/chunks v4 migration tests.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Literal, Optional

from .dataset_v4_schema import (
    SectionType,
    join_section_path,
    normalize_text_for_id,
    sha1_id,
)

SCHEMA_VERSION_RAG_CHUNK = "namu_anime_v4_rag_chunk"

EmbeddingTextVariant = Literal[
    "raw",
    "title",
    "title_section",
    "title_section_alias",
]

EMBEDDING_TEXT_VARIANTS: tuple = (
    "raw",
    "title",
    "title_section",
    "title_section_alias",
)


# ---------------------------------------------------------------- chunk_id


def _normalize_chunk_text_for_id(text: str) -> str:
    """Normalised form used inside the chunk_id hash.

    Whitespace collapse + NFKC + lowercase via ``normalize_text_for_id`` so
    cosmetic-only edits (extra spaces, capitalisation drift) do not flip the
    chunk_id.
    """
    return normalize_text_for_id(text or "")


def make_chunk_id(
    *,
    page_id: str,
    section_key: str,
    chunk_text: str,
    occurrence: int = 0,
    length: int = 16,
) -> str:
    """Order-stable chunk ID built from ``(page_id, section_key, content_hash)``.

    * ``section_key`` is Phase 1's order-stable section identifier; using it
      means chunk_ids survive section reordering as long as the same
      section_path still exists.
    * ``content_hash`` is sha1 of the normalised chunk_text (16 hex chars),
      so any meaningful edit to the chunk text invalidates the id.
    * ``occurrence`` (0, 1, 2, ...) is the deterministic disambiguator used
      only when the very same chunk_text appears multiple times within one
      section.
    """
    norm = _normalize_chunk_text_for_id(chunk_text)
    text_hash = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
    if occurrence <= 0:
        return sha1_id(page_id, section_key, text_hash, length=length)
    return sha1_id(page_id, section_key, text_hash, f"#{occurrence}", length=length)


# ---------------------------------------------------------------- embedding_text


def build_rag_embedding_text(
    *,
    variant: str,
    title: str,
    aliases: Iterable[str],
    section_path: Iterable[str],
    section_type: str,
    chunk_text: str,
) -> str:
    """Compose the ``embedding_text`` for a chunk according to ``variant``.

    The composed string is what an embedding model will see — so we keep
    the metadata header short and put the body last. Empty alias lists are
    skipped silently in the ``title_section_alias`` variant so the embedding
    doesn't carry a dangling ``별칭:`` line.
    """
    body = chunk_text or ""
    if variant == "raw":
        return body
    if variant == "title":
        return f"제목: {title}\n\n본문:\n{body}"
    section_label = join_section_path(section_path)
    if variant == "title_section":
        return (
            f"제목: {title}\n"
            f"섹션: {section_label}\n"
            f"섹션타입: {section_type}\n\n"
            f"본문:\n{body}"
        )
    if variant == "title_section_alias":
        lines: List[str] = [f"제목: {title}"]
        alias_list = [a for a in (aliases or []) if isinstance(a, str) and a.strip()]
        if alias_list:
            lines.append(f"별칭: {', '.join(alias_list)}")
        lines.append(f"섹션: {section_label}")
        lines.append(f"섹션타입: {section_type}")
        lines.append("")  # blank line before body
        lines.append("본문:")
        lines.append(body)
        return "\n".join(lines)
    raise ValueError(
        f"unknown embedding_text variant: {variant!r}; "
        f"expected one of {EMBEDDING_TEXT_VARIANTS}"
    )


# ---------------------------------------------------------------- dataclasses


@dataclass
class RagChunkMetadata:
    """Per-chunk metadata block. Mirrors a subset of ``SectionQuality``
    (``has_spoiler``, ``noise_score``, ``is_stub``, ``is_table_like``,
    ``is_list_like``) plus retrieval-relevant fields.
    """

    source_url: Optional[str] = None
    crawl_version: str = "v4"
    has_spoiler: bool = False
    text_length: int = 0
    noise_score: float = 0.0
    is_stub: bool = False
    is_table_like: bool = False
    is_list_like: bool = False


@dataclass
class RagChunkV4:
    schema_version: str = SCHEMA_VERSION_RAG_CHUNK
    chunk_id: str = ""
    doc_id: str = ""  # == page_id
    title: str = ""  # == page_title
    aliases: List[str] = field(default_factory=list)
    section_id: str = ""  # legacy, kept for backward compat
    section_key: str = ""  # Phase 1 order-stable key, preferred for joins
    section_path: List[str] = field(default_factory=list)
    section_type: SectionType = "other"
    chunk_text: str = ""
    embedding_text: str = ""
    metadata: RagChunkMetadata = field(default_factory=RagChunkMetadata)

    def to_dict(self) -> dict:
        return asdict(self)
