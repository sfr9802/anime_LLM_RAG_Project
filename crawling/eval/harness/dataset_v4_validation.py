"""Quality / coverage validation for v4 namu_anime pages and chunks.

Pure: no I/O. The CLI wraps this and emits ``validation_report.json`` and
``validation_report.md``.
"""

from __future__ import annotations

import statistics
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .dataset_v4_schema import (
    PAGE_TYPES,
    RELATIONS,
    SCHEMA_VERSION_CHUNK,
    SCHEMA_VERSION_PAGE,
    is_generic_title,
)

SHORT_CHUNK_THRESHOLD = 60


def _as_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "to_dict"):
        return item.to_dict()
    raise TypeError(f"unsupported item type for validation: {type(item).__name__}")


def _percentile(values: Sequence[int], pct: float) -> int:
    if not values:
        return 0
    sv = sorted(values)
    if len(sv) == 1:
        return sv[0]
    k = (len(sv) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sv) - 1)
    if lo == hi:
        return sv[lo]
    frac = k - lo
    return int(sv[lo] + (sv[hi] - sv[lo]) * frac)


@dataclass
class ValidationReport:
    input_count: int = 0
    pages_count: int = 0
    chunks_count: int = 0

    page_type_counts: Dict[str, int] = field(default_factory=dict)
    relation_counts: Dict[str, int] = field(default_factory=dict)

    duplicate_page_id_count: int = 0
    duplicate_chunk_id_count: int = 0

    missing_work_title_count: int = 0
    missing_page_title_count: int = 0
    missing_source_url_count: int = 0

    generic_page_title_count: int = 0
    empty_section_count: int = 0
    empty_chunk_count: int = 0
    short_chunk_count: int = 0

    chunk_char_len: Dict[str, int] = field(default_factory=lambda: {
        "min": 0, "p50": 0, "p90": 0, "p95": 0, "max": 0,
    })

    top_generic_titles: List[Tuple[str, int]] = field(default_factory=list)
    top_short_sections: List[Tuple[str, int]] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    schema_version_mismatch_pages: int = 0
    schema_version_mismatch_chunks: int = 0

    promoted_subpage_count: int = 0  # pages with discovery_reason == "subpage"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_count": self.input_count,
            "pages_count": self.pages_count,
            "chunks_count": self.chunks_count,
            "page_type_counts": self.page_type_counts,
            "relation_counts": self.relation_counts,
            "duplicate_page_id_count": self.duplicate_page_id_count,
            "duplicate_chunk_id_count": self.duplicate_chunk_id_count,
            "missing_work_title_count": self.missing_work_title_count,
            "missing_page_title_count": self.missing_page_title_count,
            "missing_source_url_count": self.missing_source_url_count,
            "generic_page_title_count": self.generic_page_title_count,
            "empty_section_count": self.empty_section_count,
            "empty_chunk_count": self.empty_chunk_count,
            "short_chunk_count": self.short_chunk_count,
            "chunk_char_len": self.chunk_char_len,
            "top_generic_titles": [list(p) for p in self.top_generic_titles],
            "top_short_sections": [list(p) for p in self.top_short_sections],
            "warnings": self.warnings,
            "schema_version_mismatch_pages": self.schema_version_mismatch_pages,
            "schema_version_mismatch_chunks": self.schema_version_mismatch_chunks,
            "promoted_subpage_count": self.promoted_subpage_count,
        }


def validate(
    pages: Iterable[Any],
    chunks: Iterable[Any],
    *,
    input_count: int = 0,
    extra_warnings: Optional[Iterable[str]] = None,
    short_threshold: int = SHORT_CHUNK_THRESHOLD,
    top_k: int = 20,
) -> ValidationReport:
    """Compute a ValidationReport over pages + chunks."""
    report = ValidationReport(input_count=input_count)

    pages_list = [_as_dict(p) for p in pages]
    chunks_list = [_as_dict(c) for c in chunks]

    report.pages_count = len(pages_list)
    report.chunks_count = len(chunks_list)

    page_type_counter: Counter = Counter()
    relation_counter: Counter = Counter()
    page_id_counter: Counter = Counter()
    generic_titles_counter: Counter = Counter()

    empty_section_count = 0

    for p in pages_list:
        ptype = p.get("page_type") or ""
        relation = p.get("relation") or ""
        page_type_counter[ptype] += 1
        relation_counter[relation] += 1

        page_id = p.get("page_id") or ""
        if page_id:
            page_id_counter[page_id] += 1

        wt = p.get("work_title")
        pt = p.get("page_title")
        if not isinstance(wt, str) or not wt.strip():
            report.missing_work_title_count += 1
        if not isinstance(pt, str) or not pt.strip():
            report.missing_page_title_count += 1
        else:
            if is_generic_title(pt):
                report.generic_page_title_count += 1
                generic_titles_counter[pt] += 1
        if not p.get("canonical_url"):
            report.missing_source_url_count += 1

        if p.get("schema_version") != SCHEMA_VERSION_PAGE:
            report.schema_version_mismatch_pages += 1

        crawl = p.get("crawl") or {}
        if isinstance(crawl, dict) and crawl.get("discovery_reason") == "subpage":
            report.promoted_subpage_count += 1

        for sec in p.get("sections") or []:
            if not isinstance(sec, dict):
                continue
            text = sec.get("text") or ""
            if not isinstance(text, str) or not text.strip():
                empty_section_count += 1

    report.empty_section_count = empty_section_count
    report.page_type_counts = dict(page_type_counter)
    report.relation_counts = dict(relation_counter)

    duplicate_page_ids = sum(c - 1 for c in page_id_counter.values() if c > 1)
    report.duplicate_page_id_count = duplicate_page_ids

    chunk_id_counter: Counter = Counter()
    char_lens: List[int] = []
    short_section_counter: Counter = Counter()
    empty_chunk_count = 0
    short_chunk_count = 0

    for ch in chunks_list:
        chunk_id = ch.get("chunk_id") or ""
        if chunk_id:
            chunk_id_counter[chunk_id] += 1
        text = ch.get("text") or ""
        char_len = ch.get("char_len")
        if not isinstance(char_len, int):
            char_len = len(text) if isinstance(text, str) else 0
        char_lens.append(char_len)

        quality = ch.get("quality") or {}
        is_empty = bool(quality.get("is_empty")) if isinstance(quality, dict) else (char_len == 0)
        is_short = bool(quality.get("is_short")) if isinstance(quality, dict) else (char_len < short_threshold)

        if is_empty or char_len == 0:
            empty_chunk_count += 1
        if is_short:
            short_chunk_count += 1
            section_path = ch.get("section_path") or []
            if isinstance(section_path, list):
                short_section_counter[" > ".join(str(s) for s in section_path) or "본문"] += 1

        if ch.get("schema_version") != SCHEMA_VERSION_CHUNK:
            report.schema_version_mismatch_chunks += 1

    report.empty_chunk_count = empty_chunk_count
    report.short_chunk_count = short_chunk_count
    duplicate_chunk_ids = sum(c - 1 for c in chunk_id_counter.values() if c > 1)
    report.duplicate_chunk_id_count = duplicate_chunk_ids

    if char_lens:
        report.chunk_char_len = {
            "min": min(char_lens),
            "p50": _percentile(char_lens, 0.5),
            "p90": _percentile(char_lens, 0.9),
            "p95": _percentile(char_lens, 0.95),
            "max": max(char_lens),
        }

    report.top_generic_titles = generic_titles_counter.most_common(top_k)
    report.top_short_sections = short_section_counter.most_common(top_k)

    if extra_warnings:
        report.warnings.extend(list(extra_warnings))
    return report


def render_markdown(report: ValidationReport) -> str:
    rd = report.to_dict()
    short_pct = (
        100.0 * rd["short_chunk_count"] / rd["chunks_count"]
        if rd["chunks_count"]
        else 0.0
    )
    empty_pct = (
        100.0 * rd["empty_chunk_count"] / rd["chunks_count"]
        if rd["chunks_count"]
        else 0.0
    )

    lines: List[str] = []
    lines.append("# namu_anime v4 migration — validation report\n")

    lines.append("## Overview\n")
    lines.append(f"- input v3 records: **{rd['input_count']}**")
    lines.append(f"- pages_v4 produced: **{rd['pages_count']}**")
    lines.append(f"- chunks_v4 produced: **{rd['chunks_count']}**")
    lines.append(f"- promoted subpages (depth >= 1): **{rd['promoted_subpage_count']}**")
    lines.append("")

    lines.append("## Page type distribution\n")
    if rd["page_type_counts"]:
        for k in sorted(rd["page_type_counts"].keys()):
            lines.append(f"- `{k}`: {rd['page_type_counts'][k]}")
    else:
        lines.append("- (no pages)")
    lines.append("")

    lines.append("## Relation distribution\n")
    if rd["relation_counts"]:
        for k in sorted(rd["relation_counts"].keys()):
            lines.append(f"- `{k}`: {rd['relation_counts'][k]}")
    else:
        lines.append("- (no pages)")
    lines.append("")

    lines.append("## Chunk length stats (chars)\n")
    cl = rd["chunk_char_len"]
    lines.append(
        f"- min={cl['min']}, p50={cl['p50']}, p90={cl['p90']}, p95={cl['p95']}, max={cl['max']}"
    )
    lines.append(
        f"- short (<{SHORT_CHUNK_THRESHOLD} chars): {rd['short_chunk_count']} ({short_pct:.1f}%)"
    )
    lines.append(
        f"- empty: {rd['empty_chunk_count']} ({empty_pct:.1f}%)"
    )
    lines.append("")

    lines.append("## Quality issues\n")
    lines.append(f"- duplicate page_id: {rd['duplicate_page_id_count']}")
    lines.append(f"- duplicate chunk_id: {rd['duplicate_chunk_id_count']}")
    lines.append(f"- missing work_title: {rd['missing_work_title_count']}")
    lines.append(f"- missing page_title: {rd['missing_page_title_count']}")
    lines.append(f"- missing canonical_url (source): {rd['missing_source_url_count']}")
    lines.append(f"- generic page_title (still pollutes): {rd['generic_page_title_count']}")
    lines.append(f"- empty section in pages: {rd['empty_section_count']}")
    lines.append(
        f"- schema mismatches: pages={rd['schema_version_mismatch_pages']}, "
        f"chunks={rd['schema_version_mismatch_chunks']}"
    )
    lines.append("")

    if rd["top_generic_titles"]:
        lines.append("## Top generic page_titles still present\n")
        for title, count in rd["top_generic_titles"][:10]:
            lines.append(f"- `{title}`: {count}")
        lines.append("")

    if rd["top_short_sections"]:
        lines.append("## Top sections producing short chunks\n")
        for section, count in rd["top_short_sections"][:10]:
            lines.append(f"- `{section}`: {count}")
        lines.append("")

    if rd["warnings"]:
        sample = rd["warnings"][:30]
        lines.append(f"## Warnings sample (first {len(sample)} of {len(rd['warnings'])})\n")
        for w in sample:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("## Suggested next steps\n")
    if rd["generic_page_title_count"] > 0:
        lines.append(
            "- Re-crawl pages whose `page_title` is still generic — they were rescued from URL/seed but the source title was unreliable."
        )
    if rd["short_chunk_count"] / max(rd["chunks_count"], 1) > 0.1:
        lines.append(
            "- Many short chunks (<60 chars). Consider chunk-merging in the next crawler revision."
        )
    if rd["missing_source_url_count"] > 0:
        lines.append(
            "- Some pages have no canonical_url; re-crawler should always store the canonical URL on the root section."
        )
    if rd["promoted_subpage_count"] == 0:
        lines.append(
            "- No subpages were promoted; verify v3 input actually has `subpages` populated."
        )
    lines.append(
        "- Index `chunks_v4.jsonl` with the `text_for_embedding` field, not raw `text`."
    )
    return "\n".join(lines).rstrip() + "\n"
