"""Phase 5 — pre-recrawl audit harness for v4 datasets.

Loads ``pages_v4.jsonl`` + ``rag_chunks.jsonl`` (required) and optionally
``split_manifest.json`` + ``sft_export_report.json``, and produces a
structured report with four blocks plus an aggregated warnings list:

* :class:`PageAudit`     — coverage / duplicate / distribution checks
* :class:`ChunkAudit`    — length stats, quality flag ratios, work skew
* :class:`ManifestAudit` — split-aware checks (when manifest provided)
* :class:`SFTAudit`      — SFT export sanity (when sft report provided)

The module is pure data — no I/O — so it stays unit-testable. CLI
wrappers in ``scripts/`` handle JSON / JSONL reading and Markdown
rendering.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .dataset_v4_schema import PAGE_TYPES, RELATIONS, SECTION_TYPES
from .split_manifest import SPLIT_NAMES, SplitManifest


SCHEMA_VERSION_CRAWL_AUDIT = "namu_anime_v4_crawl_audit"


# ---------------------------------------------------------------- thresholds


@dataclass
class AuditThresholds:
    """Knobs that drive Phase 5 §3 warnings.

    Tuned for a small/medium namu corpus. Values can be overridden via
    the CLI; defaults err on the side of surfacing a warning rather than
    suppressing it, since this audit runs *before* a re-crawl and a
    false-alarm warning is cheaper than a silent regression.
    """

    too_short_chars: int = 60
    too_long_chars: int = 4000
    work_skew_top_n: int = 10
    work_skew_warn_ratio: float = 0.30
    short_chunk_warn_ratio: float = 0.20
    unsupported_section_type_warn_ratio: float = 0.20
    aliases_missing_warn_ratio: float = 0.95  # most namu pages legitimately have no aliases
    fetched_at_missing_warn_ratio: float = 0.50
    work_title_missing_warn_ratio: float = 0.05
    query_rewrite_min_per_page: float = 0.20
    context_answer_skew_warn_ratio: float = 0.80


# ---------------------------------------------------------------- helpers


@dataclass
class LengthStats:
    """5-number summary + count + mean for a numeric field."""

    count: int = 0
    mean: float = 0.0
    median: float = 0.0
    p25: float = 0.0
    p75: float = 0.0
    min: int = 0
    max: int = 0


def _length_stats(values: List[int]) -> LengthStats:
    if not values:
        return LengthStats()
    sorted_values = sorted(values)
    n = len(sorted_values)
    return LengthStats(
        count=n,
        mean=statistics.fmean(sorted_values),
        median=statistics.median(sorted_values),
        p25=sorted_values[max(0, n // 4 - (1 if n % 4 == 0 else 0))],
        p75=sorted_values[min(n - 1, (3 * n) // 4)],
        min=sorted_values[0],
        max=sorted_values[-1],
    )


def _duplicate_keys(values: Iterable[str]) -> List[str]:
    counter: Counter = Counter(v for v in values if isinstance(v, str) and v)
    return sorted(k for k, c in counter.items() if c > 1)


# ---------------------------------------------------------------- page audit


@dataclass
class PageAudit:
    total_pages: int = 0
    page_type_distribution: Dict[str, int] = field(default_factory=dict)
    relation_distribution: Dict[str, int] = field(default_factory=dict)
    missing_work_title: int = 0
    missing_aliases: int = 0
    missing_fetched_at: int = 0
    duplicate_page_ids: List[str] = field(default_factory=list)
    duplicate_canonical_urls: List[str] = field(default_factory=list)
    duplicate_page_titles: List[str] = field(default_factory=list)
    section_count_stats: LengthStats = field(default_factory=LengthStats)
    section_type_distribution: Dict[str, int] = field(default_factory=dict)
    unknown_section_type_count: int = 0
    other_section_type_count: int = 0
    unsupported_section_type_ratio: float = 0.0


def audit_pages(
    pages: List[Dict[str, Any]],
    thresholds: AuditThresholds,
) -> Tuple[PageAudit, List[str]]:
    """Compute :class:`PageAudit` from a list of v4 page dicts."""

    warnings: List[str] = []
    page_type: Counter = Counter()
    relation: Counter = Counter()
    section_types: Counter = Counter()
    section_counts: List[int] = []

    page_ids: List[str] = []
    canonical_urls: List[str] = []
    titles: List[str] = []

    missing_work_title = 0
    missing_aliases = 0
    missing_fetched_at = 0
    unknown_section_count = 0
    other_section_count = 0
    total_sections = 0

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_ids.append(str(page.get("page_id") or ""))

        pt = page.get("page_type")
        if isinstance(pt, str):
            page_type[pt] += 1
        rel = page.get("relation")
        if isinstance(rel, str):
            relation[rel] += 1

        wt = page.get("work_title")
        if not isinstance(wt, str) or not wt.strip():
            missing_work_title += 1

        aliases = page.get("aliases")
        if not isinstance(aliases, list) or not [
            a for a in aliases if isinstance(a, str) and a.strip()
        ]:
            missing_aliases += 1

        src = page.get("source") or {}
        fetched_at = src.get("fetched_at") if isinstance(src, dict) else None
        if not isinstance(fetched_at, str) or not fetched_at.strip():
            missing_fetched_at += 1

        canonical_urls.append(str(page.get("canonical_url") or ""))
        titles.append(str(page.get("page_title") or ""))

        sections = page.get("sections") or []
        if isinstance(sections, list):
            section_counts.append(len(sections))
            for sec in sections:
                if not isinstance(sec, dict):
                    continue
                stype = sec.get("section_type")
                if not isinstance(stype, str):
                    unknown_section_count += 1
                    section_types["__missing__"] += 1
                elif stype not in SECTION_TYPES:
                    unknown_section_count += 1
                    section_types[stype] += 1
                else:
                    section_types[stype] += 1
                    if stype == "other":
                        other_section_count += 1
                total_sections += 1
        else:
            section_counts.append(0)

    total_pages = len([p for p in pages if isinstance(p, dict)])
    unsupported_ratio = (
        (unknown_section_count + other_section_count) / total_sections
        if total_sections > 0
        else 0.0
    )

    audit = PageAudit(
        total_pages=total_pages,
        page_type_distribution=dict(page_type),
        relation_distribution=dict(relation),
        missing_work_title=missing_work_title,
        missing_aliases=missing_aliases,
        missing_fetched_at=missing_fetched_at,
        duplicate_page_ids=_duplicate_keys(page_ids),
        duplicate_canonical_urls=_duplicate_keys(canonical_urls),
        duplicate_page_titles=_duplicate_keys(titles),
        section_count_stats=_length_stats(section_counts),
        section_type_distribution=dict(section_types),
        unknown_section_type_count=unknown_section_count,
        other_section_type_count=other_section_count,
        unsupported_section_type_ratio=unsupported_ratio,
    )

    # ---- warnings ------------------------------------------------------
    if total_pages == 0:
        warnings.append("pages: input contained 0 page records")
        return audit, warnings

    if audit.duplicate_page_ids:
        warnings.append(
            f"pages: {len(audit.duplicate_page_ids)} duplicated page_id(s) detected — "
            f"sample={audit.duplicate_page_ids[:3]}"
        )
    if audit.duplicate_canonical_urls:
        warnings.append(
            f"pages: {len(audit.duplicate_canonical_urls)} duplicated canonical_url(s) detected — "
            f"sample={audit.duplicate_canonical_urls[:3]}"
        )
    if audit.duplicate_page_titles:
        warnings.append(
            f"pages: {len(audit.duplicate_page_titles)} duplicated page_title(s) detected — "
            f"sample={audit.duplicate_page_titles[:3]}"
        )
    work_title_ratio = missing_work_title / total_pages
    if work_title_ratio > thresholds.work_title_missing_warn_ratio:
        warnings.append(
            f"pages: work_title missing on {missing_work_title}/{total_pages} pages "
            f"({work_title_ratio:.2%} > {thresholds.work_title_missing_warn_ratio:.0%})"
        )
    aliases_ratio = missing_aliases / total_pages
    if aliases_ratio > thresholds.aliases_missing_warn_ratio:
        warnings.append(
            f"pages: aliases missing on {missing_aliases}/{total_pages} pages "
            f"({aliases_ratio:.2%}) — consider populating aliases during the re-crawl"
        )
    fetched_ratio = missing_fetched_at / total_pages
    if fetched_ratio > thresholds.fetched_at_missing_warn_ratio:
        warnings.append(
            f"pages: source.fetched_at missing on {missing_fetched_at}/{total_pages} pages "
            f"({fetched_ratio:.2%} > {thresholds.fetched_at_missing_warn_ratio:.0%}) — "
            f"freshness is unverifiable for those pages"
        )
    if unsupported_ratio > thresholds.unsupported_section_type_warn_ratio:
        warnings.append(
            f"pages: unsupported/other section_type ratio "
            f"{unsupported_ratio:.2%} > {thresholds.unsupported_section_type_warn_ratio:.0%} "
            f"(unknown={unknown_section_count}, other={other_section_count}/{total_sections})"
        )

    return audit, warnings


# ---------------------------------------------------------------- chunk audit


@dataclass
class WorkChunkSkew:
    work_id: str
    work_title: str
    chunk_count: int
    ratio: float


@dataclass
class ChunkAudit:
    total_chunks: int = 0
    duplicate_chunk_ids: List[str] = field(default_factory=list)
    missing_doc_id: int = 0
    missing_section_id: int = 0
    text_length_stats: LengthStats = field(default_factory=LengthStats)
    too_short_count: int = 0
    too_long_count: int = 0
    too_short_ratio: float = 0.0
    too_long_ratio: float = 0.0
    is_stub_count: int = 0
    is_stub_ratio: float = 0.0
    is_table_like_count: int = 0
    is_table_like_ratio: float = 0.0
    is_list_like_count: int = 0
    is_list_like_ratio: float = 0.0
    section_type_chunk_counts: Dict[str, int] = field(default_factory=dict)
    top_work_skew: List[WorkChunkSkew] = field(default_factory=list)


def audit_chunks(
    chunks: List[Dict[str, Any]],
    thresholds: AuditThresholds,
    *,
    doc_to_work: Optional[Dict[str, Tuple[str, str]]] = None,
) -> Tuple[ChunkAudit, List[str]]:
    """Compute :class:`ChunkAudit`.

    ``doc_to_work`` (optional) is ``page_id -> (work_id, work_title)``
    used to compute the top-N work-skew block. When omitted, the skew
    block falls back to ``doc_id`` as the bucket key.
    """

    warnings: List[str] = []
    chunk_ids: List[str] = []
    text_lengths: List[int] = []
    too_short = 0
    too_long = 0
    is_stub = 0
    is_table = 0
    is_list = 0
    missing_doc = 0
    missing_section = 0
    section_type_counts: Counter = Counter()
    work_chunk_counts: Counter = Counter()
    work_titles: Dict[str, str] = {}

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        cid = chunk.get("chunk_id")
        if isinstance(cid, str):
            chunk_ids.append(cid)
        doc_id = chunk.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id.strip():
            missing_doc += 1
        section_id = chunk.get("section_id")
        if not isinstance(section_id, str) or not section_id.strip():
            missing_section += 1
        text = chunk.get("chunk_text") or ""
        if isinstance(text, str):
            length = len(text)
        else:
            length = 0
        text_lengths.append(length)
        if length < thresholds.too_short_chars:
            too_short += 1
        if length > thresholds.too_long_chars:
            too_long += 1
        meta = chunk.get("metadata") or {}
        if isinstance(meta, dict):
            if bool(meta.get("is_stub")):
                is_stub += 1
            if bool(meta.get("is_table_like")):
                is_table += 1
            if bool(meta.get("is_list_like")):
                is_list += 1
        stype = chunk.get("section_type")
        if isinstance(stype, str):
            section_type_counts[stype] += 1

        if doc_to_work and isinstance(doc_id, str):
            mapping = doc_to_work.get(doc_id.strip())
            if mapping is not None:
                work_id, work_title = mapping
                work_chunk_counts[work_id] += 1
                if work_title:
                    work_titles.setdefault(work_id, work_title)
                continue
        # Fallback: bucket by doc_id when work mapping is unavailable.
        if isinstance(doc_id, str) and doc_id.strip():
            work_chunk_counts[doc_id.strip()] += 1

    total = len([c for c in chunks if isinstance(c, dict)])
    text_stats = _length_stats(text_lengths)

    top_skew_raw = work_chunk_counts.most_common(thresholds.work_skew_top_n)
    top_work_skew = [
        WorkChunkSkew(
            work_id=wid,
            work_title=work_titles.get(wid, ""),
            chunk_count=cnt,
            ratio=(cnt / total) if total > 0 else 0.0,
        )
        for wid, cnt in top_skew_raw
    ]

    audit = ChunkAudit(
        total_chunks=total,
        duplicate_chunk_ids=_duplicate_keys(chunk_ids),
        missing_doc_id=missing_doc,
        missing_section_id=missing_section,
        text_length_stats=text_stats,
        too_short_count=too_short,
        too_long_count=too_long,
        too_short_ratio=(too_short / total) if total > 0 else 0.0,
        too_long_ratio=(too_long / total) if total > 0 else 0.0,
        is_stub_count=is_stub,
        is_stub_ratio=(is_stub / total) if total > 0 else 0.0,
        is_table_like_count=is_table,
        is_table_like_ratio=(is_table / total) if total > 0 else 0.0,
        is_list_like_count=is_list,
        is_list_like_ratio=(is_list / total) if total > 0 else 0.0,
        section_type_chunk_counts=dict(section_type_counts),
        top_work_skew=top_work_skew,
    )

    # ---- warnings ------------------------------------------------------
    if total == 0:
        warnings.append("chunks: input contained 0 chunk records")
        return audit, warnings

    if audit.duplicate_chunk_ids:
        warnings.append(
            f"chunks: {len(audit.duplicate_chunk_ids)} duplicated chunk_id(s) detected — "
            f"sample={audit.duplicate_chunk_ids[:3]}"
        )
    if missing_doc:
        warnings.append(
            f"chunks: {missing_doc}/{total} chunks have empty/missing doc_id"
        )
    if missing_section:
        warnings.append(
            f"chunks: {missing_section}/{total} chunks have empty/missing section_id"
        )
    if audit.too_short_ratio > thresholds.short_chunk_warn_ratio:
        warnings.append(
            f"chunks: too-short chunks {too_short}/{total} "
            f"({audit.too_short_ratio:.2%}) > {thresholds.short_chunk_warn_ratio:.0%} "
            f"(threshold {thresholds.too_short_chars} chars)"
        )
    if top_work_skew:
        worst = top_work_skew[0]
        if worst.ratio > thresholds.work_skew_warn_ratio:
            warnings.append(
                f"chunks: top work {worst.work_title or worst.work_id!r} owns "
                f"{worst.chunk_count}/{total} chunks ({worst.ratio:.2%} > "
                f"{thresholds.work_skew_warn_ratio:.0%}) — corpus is skewed"
            )

    return audit, warnings


# ---------------------------------------------------------------- manifest audit


@dataclass
class ManifestAudit:
    split_doc_counts: Dict[str, int] = field(default_factory=dict)
    split_chunk_counts: Dict[str, int] = field(default_factory=dict)
    split_section_type_distribution: Dict[str, Dict[str, int]] = field(default_factory=dict)
    leaked_doc_ids: List[str] = field(default_factory=list)
    leaked_group_ids: List[str] = field(default_factory=list)
    splits_missing_section_types: Dict[str, List[str]] = field(default_factory=dict)
    chunks_outside_manifest: int = 0


def audit_manifest_block(
    manifest: SplitManifest,
    pages: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    thresholds: AuditThresholds,
) -> Tuple[ManifestAudit, List[str]]:
    """Cross-reference manifest with pages + chunks for split-level checks."""
    warnings: List[str] = []

    doc_to_split: Dict[str, str] = {
        d: s for s in SPLIT_NAMES for d in manifest.doc_ids.get(s, []) or []
    }
    page_section_types: Dict[str, List[str]] = defaultdict(list)
    for page in pages:
        if not isinstance(page, dict):
            continue
        pid = page.get("page_id")
        if not isinstance(pid, str):
            continue
        for sec in page.get("sections") or []:
            if isinstance(sec, dict):
                stype = sec.get("section_type")
                if isinstance(stype, str):
                    page_section_types[pid].append(stype)

    split_section_dist: Dict[str, Counter] = {s: Counter() for s in SPLIT_NAMES}
    for pid, types in page_section_types.items():
        split = doc_to_split.get(pid)
        if split is None:
            continue
        for t in types:
            split_section_dist[split][t] += 1

    split_chunk_counts: Dict[str, int] = {s: 0 for s in SPLIT_NAMES}
    chunks_outside = 0
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        doc_id = chunk.get("doc_id")
        if not isinstance(doc_id, str):
            continue
        split = doc_to_split.get(doc_id.strip())
        if split is None:
            chunks_outside += 1
        else:
            split_chunk_counts[split] += 1

    # leakage: doc_ids appearing in more than one split list
    seen: Dict[str, str] = {}
    leaked_docs: set = set()
    for s in SPLIT_NAMES:
        for d in manifest.doc_ids.get(s, []) or []:
            prev = seen.get(d)
            if prev is not None and prev != s:
                leaked_docs.add(d)
            seen[d] = s
    seen_g: Dict[str, str] = {}
    leaked_groups: set = set()
    for s in SPLIT_NAMES:
        for g in manifest.groups.get(s, []) or []:
            prev = seen_g.get(g)
            if prev is not None and prev != s:
                leaked_groups.add(g)
            seen_g[g] = s

    # section types missing from a split (present in *another* split)
    all_types: set = set()
    for s in SPLIT_NAMES:
        all_types.update(split_section_dist[s].keys())
    splits_missing: Dict[str, List[str]] = {}
    for s in SPLIT_NAMES:
        present = set(split_section_dist[s].keys())
        missing = sorted(all_types - present)
        if missing:
            splits_missing[s] = missing

    audit = ManifestAudit(
        split_doc_counts={s: len(manifest.doc_ids.get(s, []) or []) for s in SPLIT_NAMES},
        split_chunk_counts=split_chunk_counts,
        split_section_type_distribution={
            s: dict(split_section_dist[s]) for s in SPLIT_NAMES
        },
        leaked_doc_ids=sorted(leaked_docs),
        leaked_group_ids=sorted(leaked_groups),
        splits_missing_section_types=splits_missing,
        chunks_outside_manifest=chunks_outside,
    )

    if leaked_docs:
        warnings.append(
            f"manifest: {len(leaked_docs)} doc_id(s) leak across splits — "
            f"sample={sorted(leaked_docs)[:3]}"
        )
    if leaked_groups:
        warnings.append(
            f"manifest: {len(leaked_groups)} group_id(s) leak across splits — "
            f"sample={sorted(leaked_groups)[:3]}"
        )
    if chunks_outside:
        warnings.append(
            f"manifest: {chunks_outside} chunk(s) reference doc_ids absent from the manifest"
        )
    for s in ("valid", "test"):
        if audit.split_doc_counts.get(s, 0) == 0:
            warnings.append(f"manifest: split {s!r} has 0 docs")
            continue
        if audit.split_chunk_counts.get(s, 0) == 0:
            warnings.append(f"manifest: split {s!r} has 0 chunks (chunk-level coverage gap)")
        if splits_missing.get(s):
            warnings.append(
                f"manifest: split {s!r} is missing section_types "
                f"{splits_missing[s][:5]} — coverage gap vs. other splits"
            )

    return audit, warnings


# ---------------------------------------------------------------- sft audit


@dataclass
class SFTAudit:
    query_rewrite_counts: Dict[str, int] = field(default_factory=dict)
    context_answer_counts: Dict[str, int] = field(default_factory=dict)
    skipped: Dict[str, int] = field(default_factory=dict)
    section_type_distribution: Dict[str, Dict[str, Dict[str, int]]] = field(
        default_factory=dict
    )
    query_rewrite_to_pages_ratio: float = 0.0
    context_answer_top_section_ratio: float = 0.0
    context_answer_top_section_type: str = ""


def audit_sft_block(
    sft_report: Dict[str, Any],
    page_audit: PageAudit,
    thresholds: AuditThresholds,
) -> Tuple[SFTAudit, List[str]]:
    """Sanity-check an ``sft_export_report.json`` payload."""
    warnings: List[str] = []

    counts = sft_report.get("counts") or {}
    qr_counts_raw = counts.get("query_rewrite") or {}
    ca_counts_raw = counts.get("context_answer") or {}
    qr_counts = {s: int(qr_counts_raw.get(s, 0) or 0) for s in SPLIT_NAMES}
    ca_counts = {s: int(ca_counts_raw.get(s, 0) or 0) for s in SPLIT_NAMES}
    skipped = {k: int(v) for k, v in (sft_report.get("skipped") or {}).items()}
    section_dist = sft_report.get("section_type_distribution") or {}

    qr_total = sum(qr_counts.values())
    ca_total = sum(ca_counts.values())
    qr_ratio = (qr_total / page_audit.total_pages) if page_audit.total_pages > 0 else 0.0

    # Aggregate context_answer section-type distribution across splits to
    # find the dominant section_type and its share.
    ca_section_total: Counter = Counter()
    for split, dist in (section_dist.get("context_answer") or {}).items():
        if not isinstance(dist, dict):
            continue
        for k, v in dist.items():
            try:
                ca_section_total[k] += int(v)
            except (TypeError, ValueError):
                continue
    if ca_section_total and ca_total > 0:
        top_type, top_count = ca_section_total.most_common(1)[0]
        ca_top_ratio = top_count / sum(ca_section_total.values())
    else:
        top_type, ca_top_ratio = "", 0.0

    audit = SFTAudit(
        query_rewrite_counts=qr_counts,
        context_answer_counts=ca_counts,
        skipped=skipped,
        section_type_distribution=section_dist,
        query_rewrite_to_pages_ratio=qr_ratio,
        context_answer_top_section_ratio=ca_top_ratio,
        context_answer_top_section_type=top_type,
    )

    if page_audit.total_pages > 0 and qr_ratio < thresholds.query_rewrite_min_per_page:
        warnings.append(
            f"sft: query_rewrite total {qr_total} is only {qr_ratio:.2%} of "
            f"{page_audit.total_pages} pages (< {thresholds.query_rewrite_min_per_page:.0%}) "
            f"— most pages produced no query_rewrite record (rule-templates likely too narrow)"
        )
    if ca_top_ratio > thresholds.context_answer_skew_warn_ratio:
        warnings.append(
            f"sft: context_answer top section_type {top_type!r} owns "
            f"{ca_top_ratio:.2%} of records (> {thresholds.context_answer_skew_warn_ratio:.0%}) "
            f"— learning signal is concentrated in one section type"
        )
    if skipped:
        unsupported = skipped.get("unsupported_section_type", 0)
        missing_evidence = skipped.get("missing_evidence", 0)
        if unsupported > 0 and ca_total > 0 and unsupported / max(ca_total, 1) > 1.0:
            warnings.append(
                f"sft: {unsupported} chunks skipped as unsupported_section_type "
                f"(template coverage gap)"
            )
        if missing_evidence > 0 and ca_total > 0:
            ratio = missing_evidence / (missing_evidence + ca_total)
            if ratio > 0.30:
                warnings.append(
                    f"sft: {missing_evidence}/{missing_evidence + ca_total} candidate chunks "
                    f"({ratio:.2%}) lacked extractable evidence_span — sentence-split heuristic gap"
                )

    return audit, warnings


# ---------------------------------------------------------------- top-level


@dataclass
class CrawlV4AuditReport:
    schema_version: str = SCHEMA_VERSION_CRAWL_AUDIT
    pages: PageAudit = field(default_factory=PageAudit)
    chunks: ChunkAudit = field(default_factory=ChunkAudit)
    manifest: Optional[ManifestAudit] = None
    sft: Optional[SFTAudit] = None
    thresholds: AuditThresholds = field(default_factory=AuditThresholds)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "pages": asdict(self.pages),
            "chunks": asdict(self.chunks),
            "manifest": asdict(self.manifest) if self.manifest is not None else None,
            "sft": asdict(self.sft) if self.sft is not None else None,
            "thresholds": asdict(self.thresholds),
            "warnings": list(self.warnings),
        }


def run_full_audit(
    *,
    pages: List[Dict[str, Any]],
    chunks: List[Dict[str, Any]],
    manifest: Optional[SplitManifest] = None,
    sft_report: Optional[Dict[str, Any]] = None,
    thresholds: Optional[AuditThresholds] = None,
) -> CrawlV4AuditReport:
    """One-shot helper: run all audit blocks and aggregate warnings."""
    th = thresholds or AuditThresholds()

    page_audit, w_pages = audit_pages(pages, th)

    doc_to_work: Dict[str, Tuple[str, str]] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        pid = page.get("page_id")
        if not isinstance(pid, str):
            continue
        doc_to_work[pid.strip()] = (
            str(page.get("work_id") or ""),
            str(page.get("work_title") or ""),
        )

    chunk_audit, w_chunks = audit_chunks(chunks, th, doc_to_work=doc_to_work)

    manifest_audit: Optional[ManifestAudit] = None
    w_manifest: List[str] = []
    if manifest is not None:
        manifest_audit, w_manifest = audit_manifest_block(manifest, pages, chunks, th)

    sft_audit: Optional[SFTAudit] = None
    w_sft: List[str] = []
    if sft_report is not None:
        sft_audit, w_sft = audit_sft_block(sft_report, page_audit, th)

    return CrawlV4AuditReport(
        schema_version=SCHEMA_VERSION_CRAWL_AUDIT,
        pages=page_audit,
        chunks=chunk_audit,
        manifest=manifest_audit,
        sft=sft_audit,
        thresholds=th,
        warnings=w_pages + w_chunks + w_manifest + w_sft,
    )


# ---------------------------------------------------------------- markdown


def render_markdown(report: CrawlV4AuditReport) -> str:
    """Render a human-readable Markdown summary of the audit report."""
    lines: List[str] = []
    p = report.pages
    c = report.chunks

    lines.append("# Crawl V4 Audit Report")
    lines.append("")
    lines.append(f"- schema_version: `{report.schema_version}`")
    lines.append(f"- warnings: **{len(report.warnings)}**")
    lines.append("")

    # Pages -------------------------------------------------------------
    lines.append("## Pages")
    lines.append(f"- total_pages: **{p.total_pages}**")
    lines.append(f"- missing work_title: {p.missing_work_title}")
    lines.append(f"- missing aliases: {p.missing_aliases}")
    lines.append(f"- missing source.fetched_at: {p.missing_fetched_at}")
    if p.duplicate_page_ids:
        lines.append(
            f"- duplicate page_ids ({len(p.duplicate_page_ids)}): "
            f"{p.duplicate_page_ids[:5]}"
        )
    if p.duplicate_canonical_urls:
        lines.append(
            f"- duplicate canonical_urls ({len(p.duplicate_canonical_urls)}): "
            f"{p.duplicate_canonical_urls[:5]}"
        )
    if p.duplicate_page_titles:
        lines.append(
            f"- duplicate page_titles ({len(p.duplicate_page_titles)}): "
            f"{p.duplicate_page_titles[:5]}"
        )
    lines.append(
        f"- section_count: count={p.section_count_stats.count} "
        f"mean={p.section_count_stats.mean:.2f} "
        f"median={p.section_count_stats.median:.0f} "
        f"min={p.section_count_stats.min} max={p.section_count_stats.max}"
    )
    lines.append(
        f"- unsupported_section_type_ratio: "
        f"{p.unsupported_section_type_ratio:.2%} "
        f"(unknown={p.unknown_section_type_count}, other={p.other_section_type_count})"
    )
    lines.append("")
    lines.append("### page_type distribution")
    for k, v in sorted(p.page_type_distribution.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {k}: {v}")
    lines.append("")
    lines.append("### section_type distribution")
    for k, v in sorted(p.section_type_distribution.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {k}: {v}")
    lines.append("")

    # Chunks ------------------------------------------------------------
    lines.append("## Chunks")
    lines.append(f"- total_chunks: **{c.total_chunks}**")
    lines.append(
        f"- text_length: count={c.text_length_stats.count} "
        f"mean={c.text_length_stats.mean:.1f} "
        f"median={c.text_length_stats.median:.0f} "
        f"p25={c.text_length_stats.p25} p75={c.text_length_stats.p75} "
        f"min={c.text_length_stats.min} max={c.text_length_stats.max}"
    )
    lines.append(
        f"- too_short ({c.too_short_ratio:.2%}): {c.too_short_count}, "
        f"too_long ({c.too_long_ratio:.2%}): {c.too_long_count}"
    )
    lines.append(
        f"- is_stub: {c.is_stub_count} ({c.is_stub_ratio:.2%}), "
        f"is_table_like: {c.is_table_like_count} ({c.is_table_like_ratio:.2%}), "
        f"is_list_like: {c.is_list_like_count} ({c.is_list_like_ratio:.2%})"
    )
    if c.duplicate_chunk_ids:
        lines.append(
            f"- duplicate chunk_ids ({len(c.duplicate_chunk_ids)}): "
            f"{c.duplicate_chunk_ids[:5]}"
        )
    lines.append("")
    lines.append("### top work skew")
    for w in c.top_work_skew:
        label = w.work_title or w.work_id
        lines.append(f"- {label}: {w.chunk_count} chunks ({w.ratio:.2%})")
    lines.append("")
    lines.append("### chunks by section_type")
    for k, v in sorted(c.section_type_chunk_counts.items(), key=lambda kv: -kv[1]):
        lines.append(f"- {k}: {v}")
    lines.append("")

    # Manifest ---------------------------------------------------------
    if report.manifest is not None:
        m = report.manifest
        lines.append("## Manifest")
        lines.append(
            f"- doc_counts: train={m.split_doc_counts.get('train',0)} "
            f"valid={m.split_doc_counts.get('valid',0)} "
            f"test={m.split_doc_counts.get('test',0)}"
        )
        lines.append(
            f"- chunk_counts: train={m.split_chunk_counts.get('train',0)} "
            f"valid={m.split_chunk_counts.get('valid',0)} "
            f"test={m.split_chunk_counts.get('test',0)}"
        )
        if m.leaked_doc_ids:
            lines.append(f"- leaked_doc_ids: {len(m.leaked_doc_ids)}")
        if m.leaked_group_ids:
            lines.append(f"- leaked_group_ids: {len(m.leaked_group_ids)}")
        if m.chunks_outside_manifest:
            lines.append(f"- chunks_outside_manifest: {m.chunks_outside_manifest}")
        if m.splits_missing_section_types:
            for s, missing in m.splits_missing_section_types.items():
                lines.append(f"- {s} missing section_types: {missing}")
        lines.append("")

    # SFT --------------------------------------------------------------
    if report.sft is not None:
        s = report.sft
        lines.append("## SFT")
        lines.append(
            f"- query_rewrite: train={s.query_rewrite_counts.get('train',0)} "
            f"valid={s.query_rewrite_counts.get('valid',0)} "
            f"test={s.query_rewrite_counts.get('test',0)} "
            f"(per-page {s.query_rewrite_to_pages_ratio:.2%})"
        )
        lines.append(
            f"- context_answer: train={s.context_answer_counts.get('train',0)} "
            f"valid={s.context_answer_counts.get('valid',0)} "
            f"test={s.context_answer_counts.get('test',0)}"
        )
        if s.context_answer_top_section_type:
            lines.append(
                f"- context_answer top section_type: "
                f"`{s.context_answer_top_section_type}` "
                f"({s.context_answer_top_section_ratio:.2%})"
            )
        if s.skipped:
            sk = ", ".join(f"{k}={v}" for k, v in sorted(s.skipped.items()))
            lines.append(f"- skipped: {sk}")
        lines.append("")

    # Warnings ---------------------------------------------------------
    lines.append("## Warnings")
    if not report.warnings:
        lines.append("- (none)")
    else:
        for w in report.warnings:
            lines.append(f"- {w}")
    lines.append("")

    return "\n".join(lines)
