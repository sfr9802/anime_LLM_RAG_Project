"""Phase 4 — SFT JSONL record schema.

Two record schemas, both wrapping an OpenAI-style ``messages`` envelope:

* :data:`SCHEMA_VERSION_SFT_QUERY_REWRITE` — user query → search-friendly JSON
* :data:`SCHEMA_VERSION_SFT_CONTEXT_ANSWER` — context+question → answer

The ``source`` block keeps provenance back to the originating chunk so a
later audit can trace each record to its evidence chunk. The same
:class:`SFTSource` dataclass serves both schemas; ``evidence_span`` is
omitted from the serialised output when it is ``None`` (i.e. for
query_rewrite records).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


SCHEMA_VERSION_SFT_QUERY_REWRITE = "namu_anime_v4_sft_query_rewrite"
SCHEMA_VERSION_SFT_CONTEXT_ANSWER = "namu_anime_v4_sft_context_answer"
SCHEMA_VERSION_SFT_EXPORT_REPORT = "namu_anime_v4_sft_export_report"

ROLE_SYSTEM = "system"
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
VALID_ROLES = frozenset({ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT})


@dataclass
class SFTMessage:
    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class SFTSource:
    """Provenance block. ``evidence_span`` is optional — set for
    context_answer records, ``None`` for query_rewrite."""

    doc_id: str
    section_id: str = ""
    section_key: str = ""
    chunk_id: str = ""
    split: str = ""
    evidence_span: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "doc_id": self.doc_id,
            "section_id": self.section_id,
            "section_key": self.section_key,
            "chunk_id": self.chunk_id,
            "split": self.split,
        }
        if self.evidence_span is not None:
            d["evidence_span"] = self.evidence_span
        return d


@dataclass
class SFTRecord:
    schema_version: str
    messages: List[SFTMessage]
    source: SFTSource

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "messages": [m.to_dict() for m in self.messages],
            "source": self.source.to_dict(),
        }


# ---------------------------------------------------------------- export report


@dataclass
class SFTSplitCounts:
    train: int = 0
    valid: int = 0
    test: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {"train": self.train, "valid": self.valid, "test": self.test}


@dataclass
class SFTSkipped:
    """Counters for chunks that were skipped during export.

    The categories match Phase 4 spec §9 and are kept stable so a
    downstream dashboard can chart them over time:

    * ``low_quality`` — ``is_stub`` / ``is_table_like`` chunks (default-skipped)
    * ``too_short`` — chunk text below ``min_context_chars``
    * ``missing_manifest`` — chunk's ``doc_id`` not in the split manifest
      (only reachable with ``--allow-missing-docs``; otherwise raises)
    * ``missing_evidence`` — supported section_type but no extractable
      evidence span
    * ``unsupported_section_type`` — section_type not in our rule table
    """

    low_quality: int = 0
    too_short: int = 0
    missing_manifest: int = 0
    missing_evidence: int = 0
    unsupported_section_type: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "low_quality": self.low_quality,
            "too_short": self.too_short,
            "missing_manifest": self.missing_manifest,
            "missing_evidence": self.missing_evidence,
            "unsupported_section_type": self.unsupported_section_type,
        }


@dataclass
class SFTExportReport:
    schema_version: str = SCHEMA_VERSION_SFT_EXPORT_REPORT
    counts: Dict[str, SFTSplitCounts] = field(default_factory=dict)
    skipped: SFTSkipped = field(default_factory=SFTSkipped)
    section_type_distribution: Dict[str, Dict[str, Dict[str, int]]] = field(
        default_factory=dict
    )
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "counts": {k: v.to_dict() for k, v in self.counts.items()},
            "skipped": self.skipped.to_dict(),
            "section_type_distribution": self.section_type_distribution,
            "warnings": list(self.warnings),
        }
