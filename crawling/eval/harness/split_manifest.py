"""Phase 3 / 3.5 — group-level train/valid/test split manifest.

Given a v4 pages JSONL, this module produces a deterministic
:class:`SplitManifest` that groups pages by ``work_id`` (the canonical
work-level identifier already populated by the v3->v4 converter), shuffles
*groups* with a fixed seed, and assigns whole groups to train / valid /
test according to user ratios.

The hard rule (see Phase 3 spec §2 and §10): **never split chunks at the
chunk level**. Splitting groups instead of pages keeps a work's main
page, character pages, setting pages, and episode pages in the same
split — without that, the same proper nouns would leak across train and
test and corrupt evaluation.

Phase 3.5 additions (additive / backward-compatible):

* :class:`GroupingAudit` records work_id coverage and fallback samples so
  large-corpus runs can detect work_id regressions.
* :class:`DistributionReport` records per-split page_type / section_type
  / group_size statistics (computed from pages and optional rag_chunks).
* :func:`extend_split_manifest` adds new groups to an existing manifest
  while preserving the prior split assignment of every base group.

Main entry points:

* :func:`build_split_manifest` builds the manifest from a page iterable
* :func:`extend_split_manifest` adds new groups onto an existing manifest
* :func:`apply_manifest_to_chunks` routes chunks (or rag_chunks dicts)
  to per-split lists using the manifest's ``doc_to_group`` mapping
* :func:`audit_manifest` produces a leakage / coverage / distribution
  report. Pass ``pages`` (and optional ``chunks``) to populate the
  distribution block.

Everything here is pure (no I/O); the CLI wrappers in ``scripts/``
handle JSONL.
"""

from __future__ import annotations

import math
import random
from collections import Counter, OrderedDict, defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

SCHEMA_VERSION_SPLIT_MANIFEST = "namu_anime_v4_split_manifest"
SCHEMA_VERSION_SPLIT_REPORT = "namu_anime_v4_split_report"

DEFAULT_STRATEGY = "group_level_split"
DEFAULT_SEED = 42
DEFAULT_TRAIN_RATIO = 0.8
DEFAULT_VALID_RATIO = 0.1
DEFAULT_TEST_RATIO = 0.1
RATIO_TOLERANCE = 1e-6
SPLIT_NAMES: Tuple[str, str, str] = ("train", "valid", "test")

# Phase 3.5: how many samples to keep in fallback_doc_ids_sample / titles.
DEFAULT_FALLBACK_SAMPLE_SIZE = 10
# Default warning threshold. CLI exposes --max-fallback-ratio; passing
# None (the in-process default) disables the threshold check.
DEFAULT_MAX_FALLBACK_RATIO: Optional[float] = None


# ---------------------------------------------------------------- group_id


def derive_group_id(page: Dict[str, Any]) -> Tuple[Optional[str], bool]:
    """Pick a stable group key for a page.

    Priority (per Phase 3 §4):
        1. ``page["work_id"]`` (already populated by the v3->v4 converter
           as ``sha1_id(work_title)`` and shared by main + subpages of
           the same work).
        2. fallback: ``page["page_id"]`` (single-doc group; reported via
           ``used_fallback=True`` so the audit can count fallbacks).

    Returns ``(group_id, used_fallback)``. Returns ``(None, True)`` when
    neither field is usable — the caller should drop the page in that
    case rather than inventing an ID.
    """
    work_id = page.get("work_id")
    if isinstance(work_id, str) and work_id.strip():
        return work_id.strip(), False
    page_id = page.get("page_id")
    if isinstance(page_id, str) and page_id.strip():
        return page_id.strip(), True
    return None, True


# ---------------------------------------------------------------- dataclasses


@dataclass
class SplitCounts:
    train: int = 0
    valid: int = 0
    test: int = 0
    total: int = 0


@dataclass
class SplitManifestCounts:
    groups: SplitCounts = field(default_factory=SplitCounts)
    docs: SplitCounts = field(default_factory=SplitCounts)


@dataclass
class GroupingAudit:
    """Phase 3.5 — work_id / group_id coverage audit.

    ``work_id_coverage_ratio`` is the fraction of input docs whose
    ``work_id`` was present (so they joined a real work-level group rather
    than the page_id fallback singleton). The two ``*_sample`` lists
    surface fallback evidence for the user to investigate without dumping
    the full corpus.
    """

    total_docs: int = 0
    work_id_present_docs: int = 0
    work_id_missing_docs: int = 0
    work_id_coverage_ratio: float = 0.0
    fallback_group_count: int = 0
    fallback_doc_ids_sample: List[str] = field(default_factory=list)
    fallback_titles_sample: List[str] = field(default_factory=list)


@dataclass
class GroupSizeStats:
    """Per-split group size statistics. ``*_chunks_per_group`` stays at 0
    when the audit had no rag_chunks input (chunk-level distribution is
    optional)."""

    avg_docs_per_group: float = 0.0
    max_docs_per_group: int = 0
    avg_chunks_per_group: float = 0.0
    max_chunks_per_group: int = 0


@dataclass
class DistributionReport:
    """Phase 3.5 — per-split distribution snapshot.

    ``chunks`` and ``section_type`` are populated only when the audit was
    run with a rag_chunks input. ``page_type`` and ``group_size.docs_*``
    are computed from pages alone, so they are always available.
    """

    chunks: Dict[str, int] = field(default_factory=dict)
    page_type: Dict[str, Dict[str, int]] = field(default_factory=dict)
    section_type: Dict[str, Dict[str, int]] = field(default_factory=dict)
    group_size: Dict[str, GroupSizeStats] = field(default_factory=dict)


@dataclass
class ExtensionAudit:
    """Phase 3.5 — diff produced by :func:`extend_split_manifest`.

    ``missing_groups_from_input`` lists base groups that are no longer
    present in the current input. ``dropped_doc_ids`` /
    ``dropped_group_ids`` are populated only when ``--drop-missing-docs``
    is set.
    """

    base_groups: int = 0
    new_groups: int = 0
    preserved_groups: int = 0
    missing_groups_from_input: List[str] = field(default_factory=list)
    added_groups: Dict[str, List[str]] = field(default_factory=dict)
    dropped_doc_ids: List[str] = field(default_factory=list)
    dropped_group_ids: List[str] = field(default_factory=list)


@dataclass
class SplitManifest:
    schema_version: str = SCHEMA_VERSION_SPLIT_MANIFEST
    strategy: str = DEFAULT_STRATEGY
    seed: int = DEFAULT_SEED
    ratios: Dict[str, float] = field(default_factory=dict)
    counts: SplitManifestCounts = field(default_factory=SplitManifestCounts)
    groups: Dict[str, List[str]] = field(default_factory=dict)
    doc_ids: Dict[str, List[str]] = field(default_factory=dict)
    doc_to_group: Dict[str, str] = field(default_factory=dict)
    fallback_group_count: int = 0
    # Phase 3.5: GroupingAudit produced at build/extend time. Optional so
    # manifests serialised by Phase 3 still round-trip cleanly.
    grouping: Optional[GroupingAudit] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SplitReportLeakage:
    doc_id_overlap: List[str] = field(default_factory=list)
    group_id_overlap: List[str] = field(default_factory=list)


@dataclass
class SplitReport:
    schema_version: str = SCHEMA_VERSION_SPLIT_REPORT
    total_docs: int = 0
    total_groups: int = 0
    split_doc_counts: Dict[str, int] = field(default_factory=dict)
    split_group_counts: Dict[str, int] = field(default_factory=dict)
    leakage: SplitReportLeakage = field(default_factory=SplitReportLeakage)
    fallback_group_count: int = 0
    # Phase 3.5: optional audit blocks. Set only when the relevant input
    # was supplied to ``audit_manifest``.
    grouping: Optional[GroupingAudit] = None
    distribution: Optional[DistributionReport] = None
    extension: Optional[ExtensionAudit] = None
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------- ratio split


def _validate_ratios(train: float, valid: float, test: float) -> None:
    if any(r < 0 for r in (train, valid, test)):
        raise ValueError(
            f"all ratios must be >= 0; got train={train}, valid={valid}, test={test}"
        )
    total = train + valid + test
    if abs(total - 1.0) > RATIO_TOLERANCE:
        raise ValueError(
            f"ratios must sum to 1.0 (within {RATIO_TOLERANCE}); "
            f"got train+valid+test = {total}"
        )


def _allocate_split_sizes(
    n_groups: int,
    *,
    train: float,
    valid: float,
    test: float,
) -> Tuple[int, int, int, List[str]]:
    """Return ``(n_train, n_valid, n_test, warnings)`` for ``n_groups`` items.

    ``valid`` and ``test`` use ``ceil`` so a non-zero ratio always yields
    at least 1 group when the corpus is small enough; ``train`` absorbs
    whatever is left. Edge-case warnings (empty splits, train < 0) are
    captured in the returned list rather than raised — the caller decides
    whether to surface them.
    """
    warnings: List[str] = []
    if n_groups <= 0:
        return 0, 0, 0, warnings

    n_valid = math.ceil(n_groups * valid) if valid > 0 else 0
    n_test = math.ceil(n_groups * test) if test > 0 else 0
    n_train = n_groups - n_valid - n_test

    if n_train < 0:
        # Pathological: valid+test ratios consumed everything. Trim test
        # then valid to keep train >= 0; warn so the user can adjust.
        deficit = -n_train
        take_from_test = min(n_test, deficit)
        n_test -= take_from_test
        deficit -= take_from_test
        if deficit > 0:
            n_valid -= deficit
        n_train = n_groups - n_valid - n_test
        warnings.append(
            f"train allocation became negative under ratios "
            f"({train}, {valid}, {test}); trimmed valid/test to keep train >= 0"
        )

    if valid > 0 and n_valid == 0:
        warnings.append(
            f"valid split is empty (n_groups={n_groups}, valid_ratio={valid})"
        )
    if test > 0 and n_test == 0:
        warnings.append(
            f"test split is empty (n_groups={n_groups}, test_ratio={test})"
        )
    if train > 0 and n_train == 0:
        warnings.append(
            f"train split is empty (n_groups={n_groups}, train_ratio={train})"
        )
    return n_train, n_valid, n_test, warnings


# ---------------------------------------------------------------- build


def build_split_manifest(
    pages: Iterable[Dict[str, Any]],
    *,
    seed: int = DEFAULT_SEED,
    train_ratio: float = DEFAULT_TRAIN_RATIO,
    valid_ratio: float = DEFAULT_VALID_RATIO,
    test_ratio: float = DEFAULT_TEST_RATIO,
    max_fallback_ratio: Optional[float] = DEFAULT_MAX_FALLBACK_RATIO,
    fail_on_high_fallback: bool = False,
    fallback_sample_size: int = DEFAULT_FALLBACK_SAMPLE_SIZE,
) -> SplitManifest:
    """Build a deterministic group-level split manifest from a page iterable.

    The manifest groups pages by ``derive_group_id`` (work_id with
    page_id fallback), shuffles the unique group ids using
    ``random.Random(seed)``, and assigns whole groups to train/valid/test.

    Phase 3.5 additions: returns a populated :class:`GroupingAudit` on
    the manifest. When ``max_fallback_ratio`` is set and the actual
    work_id-fallback ratio exceeds it, a warning is recorded; with
    ``fail_on_high_fallback=True`` the function raises ``ValueError``
    instead of warning.

    Raises:
        ValueError: when ratios are invalid, no usable pages were found,
        any single doc ended up in more than one split (defensive
        post-check), or the fallback ratio exceeds
        ``max_fallback_ratio`` and ``fail_on_high_fallback`` is set.
    """
    _validate_ratios(train_ratio, valid_ratio, test_ratio)

    warnings: List[str] = []

    # Preserve discovery order so the manifest is deterministic relative
    # to a given input order *before* the seeded shuffle.
    doc_to_group: "OrderedDict[str, str]" = OrderedDict()
    group_to_docs: "OrderedDict[str, List[str]]" = OrderedDict()
    fallback_groups: set = set()
    work_id_present = 0
    work_id_missing = 0
    fallback_doc_id_samples: List[str] = []
    fallback_title_samples: List[str] = []

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = page.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip():
            warnings.append("skipped page without page_id")
            continue
        page_id = page_id.strip()
        if page_id in doc_to_group:
            warnings.append(f"duplicate page_id {page_id!r}; later occurrence ignored")
            continue
        group_id, used_fallback = derive_group_id(page)
        if not group_id:
            warnings.append(f"skipped page {page_id!r}: no derivable group_id")
            continue
        doc_to_group[page_id] = group_id
        group_to_docs.setdefault(group_id, []).append(page_id)
        if used_fallback:
            fallback_groups.add(group_id)
            work_id_missing += 1
            if len(fallback_doc_id_samples) < fallback_sample_size:
                fallback_doc_id_samples.append(page_id)
                title = page.get("page_title")
                fallback_title_samples.append(
                    title if isinstance(title, str) else ""
                )
        else:
            work_id_present += 1

    if not doc_to_group:
        raise ValueError("no usable pages: input had 0 documents with page_id+group_id")

    fallback_count = len(fallback_groups)
    total_input_docs = work_id_present + work_id_missing
    coverage_ratio = (
        (work_id_present / total_input_docs) if total_input_docs > 0 else 0.0
    )
    if fallback_count:
        warnings.append(
            f"{fallback_count} group(s) used the page_id fallback because work_id was missing"
        )

    fallback_ratio = (
        (work_id_missing / total_input_docs) if total_input_docs > 0 else 0.0
    )
    if max_fallback_ratio is not None and fallback_ratio > max_fallback_ratio:
        msg = (
            f"work_id fallback ratio {fallback_ratio:.4f} exceeds threshold "
            f"{max_fallback_ratio:.4f} ({work_id_missing}/{total_input_docs} docs missing work_id)"
        )
        if fail_on_high_fallback:
            raise ValueError(msg)
        warnings.append(msg)

    grouping_audit = GroupingAudit(
        total_docs=total_input_docs,
        work_id_present_docs=work_id_present,
        work_id_missing_docs=work_id_missing,
        work_id_coverage_ratio=coverage_ratio,
        fallback_group_count=fallback_count,
        fallback_doc_ids_sample=list(fallback_doc_id_samples),
        fallback_titles_sample=list(fallback_title_samples),
    )

    # Deterministic shuffle: sort group ids canonically before shuffling
    # so the output does not depend on input dict iteration order.
    ordered_groups = sorted(group_to_docs.keys())
    rng = random.Random(seed)
    rng.shuffle(ordered_groups)

    n_groups = len(ordered_groups)
    n_train, n_valid, n_test, alloc_warnings = _allocate_split_sizes(
        n_groups,
        train=train_ratio,
        valid=valid_ratio,
        test=test_ratio,
    )
    warnings.extend(alloc_warnings)

    train_groups = sorted(ordered_groups[:n_train])
    valid_groups = sorted(ordered_groups[n_train : n_train + n_valid])
    test_groups = sorted(ordered_groups[n_train + n_valid : n_train + n_valid + n_test])

    def _docs_for(groups: List[str]) -> List[str]:
        out: List[str] = []
        for g in groups:
            out.extend(group_to_docs.get(g, []))
        return sorted(set(out))

    train_docs = _docs_for(train_groups)
    valid_docs = _docs_for(valid_groups)
    test_docs = _docs_for(test_groups)

    # Defensive post-check: no doc in more than one split.
    seen_docs: Dict[str, str] = {}
    for split_name, docs in (
        ("train", train_docs),
        ("valid", valid_docs),
        ("test", test_docs),
    ):
        for d in docs:
            prev = seen_docs.get(d)
            if prev is not None and prev != split_name:
                raise ValueError(
                    f"doc_id {d!r} appears in both {prev!r} and {split_name!r} splits"
                )
            seen_docs[d] = split_name

    total_groups = len(train_groups) + len(valid_groups) + len(test_groups)
    total_docs = len(train_docs) + len(valid_docs) + len(test_docs)

    return SplitManifest(
        schema_version=SCHEMA_VERSION_SPLIT_MANIFEST,
        strategy=DEFAULT_STRATEGY,
        seed=seed,
        ratios={"train": train_ratio, "valid": valid_ratio, "test": test_ratio},
        counts=SplitManifestCounts(
            groups=SplitCounts(
                train=len(train_groups),
                valid=len(valid_groups),
                test=len(test_groups),
                total=total_groups,
            ),
            docs=SplitCounts(
                train=len(train_docs),
                valid=len(valid_docs),
                test=len(test_docs),
                total=total_docs,
            ),
        ),
        groups={"train": train_groups, "valid": valid_groups, "test": test_groups},
        doc_ids={"train": train_docs, "valid": valid_docs, "test": test_docs},
        doc_to_group=dict(doc_to_group),
        fallback_group_count=fallback_count,
        grouping=grouping_audit,
        warnings=warnings,
    )


# ---------------------------------------------------------------- audit


def _overlap_keys(*lists: Iterable[str]) -> List[str]:
    """Return the sorted list of values that appear in more than one input list."""
    counts: Dict[str, int] = defaultdict(int)
    for lst in lists:
        for v in set(lst):  # within-list duplicates do not count
            counts[v] += 1
    return sorted(k for k, c in counts.items() if c > 1)


def _compute_distribution(
    manifest: SplitManifest,
    pages: Iterable[Dict[str, Any]],
    chunks: Optional[Iterable[Dict[str, Any]]] = None,
) -> Tuple[DistributionReport, List[str]]:
    """Aggregate per-split distribution stats from pages (and chunks)."""

    doc_to_split: Dict[str, str] = {}
    for s in SPLIT_NAMES:
        for d in manifest.doc_ids.get(s, []):
            doc_to_split[d] = s

    page_type_counts: Dict[str, "Counter"] = {s: Counter() for s in SPLIT_NAMES}
    docs_per_group: Dict[str, int] = defaultdict(int)
    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = page.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip():
            continue
        page_id = page_id.strip()
        split = doc_to_split.get(page_id)
        if split is None:
            continue
        page_type = page.get("page_type") or "other"
        if not isinstance(page_type, str):
            page_type = "other"
        page_type_counts[split][page_type] += 1
        gid = manifest.doc_to_group.get(page_id)
        if gid:
            docs_per_group[gid] += 1

    chunk_counts: Dict[str, int] = {s: 0 for s in SPLIT_NAMES}
    section_type_counts: Dict[str, "Counter"] = {s: Counter() for s in SPLIT_NAMES}
    chunks_per_group: Dict[str, int] = defaultdict(int)
    chunks_provided = chunks is not None
    if chunks is not None:
        for chunk in chunks:
            if not isinstance(chunk, dict):
                continue
            doc_id = chunk.get("doc_id")
            if not isinstance(doc_id, str) or not doc_id.strip():
                continue
            doc_id = doc_id.strip()
            split = doc_to_split.get(doc_id)
            if split is None:
                continue
            chunk_counts[split] += 1
            sec_type = chunk.get("section_type") or "other"
            if not isinstance(sec_type, str):
                sec_type = "other"
            section_type_counts[split][sec_type] += 1
            gid = manifest.doc_to_group.get(doc_id)
            if gid:
                chunks_per_group[gid] += 1

    group_size: Dict[str, GroupSizeStats] = {}
    for s in SPLIT_NAMES:
        groups_in_split = manifest.groups.get(s, []) or []
        n = len(groups_in_split)
        if n == 0:
            group_size[s] = GroupSizeStats()
            continue
        docs_total = sum(docs_per_group.get(g, 0) for g in groups_in_split)
        max_docs = max((docs_per_group.get(g, 0) for g in groups_in_split), default=0)
        chunks_total = sum(chunks_per_group.get(g, 0) for g in groups_in_split)
        max_chunks = max(
            (chunks_per_group.get(g, 0) for g in groups_in_split), default=0
        )
        group_size[s] = GroupSizeStats(
            avg_docs_per_group=docs_total / n,
            max_docs_per_group=max_docs,
            avg_chunks_per_group=(chunks_total / n) if chunks_provided else 0.0,
            max_chunks_per_group=max_chunks if chunks_provided else 0,
        )

    distribution = DistributionReport(
        chunks=dict(chunk_counts) if chunks_provided else {},
        page_type={s: dict(page_type_counts[s]) for s in SPLIT_NAMES},
        section_type=(
            {s: dict(section_type_counts[s]) for s in SPLIT_NAMES}
            if chunks_provided
            else {}
        ),
        group_size=group_size,
    )

    warnings: List[str] = []
    for s in ("valid", "test"):
        if not page_type_counts[s]:
            warnings.append(
                f"distribution: {s} split has 0 pages with a known page_type"
            )
        if chunks_provided and chunk_counts[s] == 0:
            warnings.append(
                f"distribution: {s} split has 0 chunks (chunk-level coverage gap)"
            )
    return distribution, warnings


def audit_manifest(
    manifest: SplitManifest,
    *,
    pages: Optional[Iterable[Dict[str, Any]]] = None,
    chunks: Optional[Iterable[Dict[str, Any]]] = None,
    extension: Optional[ExtensionAudit] = None,
) -> SplitReport:
    """Compute a leakage / coverage / distribution report for a manifest.

    The audit is independent from ``build_split_manifest`` (which raises
    on overlap) so a manifest loaded from disk can be re-checked.

    Phase 3.5: pass ``pages`` (and optionally ``chunks``) to populate the
    distribution block. The grouping block is read off
    ``manifest.grouping`` if present (set by ``build_split_manifest`` /
    ``extend_split_manifest``); for legacy manifests loaded from disk it
    will simply be absent.
    """
    train_docs = manifest.doc_ids.get("train", [])
    valid_docs = manifest.doc_ids.get("valid", [])
    test_docs = manifest.doc_ids.get("test", [])
    train_groups = manifest.groups.get("train", [])
    valid_groups = manifest.groups.get("valid", [])
    test_groups = manifest.groups.get("test", [])

    doc_overlap = _overlap_keys(train_docs, valid_docs, test_docs)
    group_overlap = _overlap_keys(train_groups, valid_groups, test_groups)

    extra_warnings: List[str] = []
    distribution: Optional[DistributionReport] = None
    if pages is not None:
        distribution, dist_warnings = _compute_distribution(
            manifest, pages, chunks
        )
        extra_warnings.extend(dist_warnings)

    return SplitReport(
        schema_version=SCHEMA_VERSION_SPLIT_REPORT,
        total_docs=len(train_docs) + len(valid_docs) + len(test_docs),
        total_groups=len(train_groups) + len(valid_groups) + len(test_groups),
        split_doc_counts={
            "train": len(train_docs),
            "valid": len(valid_docs),
            "test": len(test_docs),
        },
        split_group_counts={
            "train": len(train_groups),
            "valid": len(valid_groups),
            "test": len(test_groups),
        },
        leakage=SplitReportLeakage(
            doc_id_overlap=doc_overlap,
            group_id_overlap=group_overlap,
        ),
        fallback_group_count=manifest.fallback_group_count,
        grouping=manifest.grouping,
        distribution=distribution,
        extension=extension,
        warnings=list(manifest.warnings) + extra_warnings,
    )


# ---------------------------------------------------------------- apply


def _doc_to_split_lookup(manifest: SplitManifest) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for split in SPLIT_NAMES:
        for d in manifest.doc_ids.get(split, []):
            out[d] = split
    return out


@dataclass
class SplitApplyResult:
    """Streaming-friendly counts emitted by :func:`apply_manifest_to_chunks_iter`.

    ``missing`` is the number of chunks whose ``doc_id`` was not present
    in the manifest. When ``allow_missing=False`` the iterator raises on
    the first such chunk; when ``True`` they are silently dropped and
    counted here.
    """

    train: int = 0
    valid: int = 0
    test: int = 0
    missing: int = 0
    missing_doc_ids: List[str] = field(default_factory=list)


def apply_manifest_to_chunks(
    chunks: Iterable[Dict[str, Any]],
    manifest: SplitManifest,
    *,
    allow_missing: bool = False,
) -> Tuple[Dict[str, List[Dict[str, Any]]], SplitApplyResult]:
    """In-memory routing of chunk dicts to per-split lists.

    Returns ``(per_split, summary)``. Each chunk is preserved verbatim —
    routing only depends on ``chunk["doc_id"]``.
    """
    lookup = _doc_to_split_lookup(manifest)
    out: Dict[str, List[Dict[str, Any]]] = {s: [] for s in SPLIT_NAMES}
    summary = SplitApplyResult()
    seen_missing: "OrderedDict[str, None]" = OrderedDict()

    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        doc_id = chunk.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id:
            if allow_missing:
                summary.missing += 1
                continue
            raise ValueError("chunk missing 'doc_id'")
        split = lookup.get(doc_id)
        if split is None:
            if allow_missing:
                summary.missing += 1
                seen_missing.setdefault(doc_id, None)
                continue
            raise ValueError(
                f"chunk doc_id {doc_id!r} not present in manifest "
                f"(use allow_missing=True to skip)"
            )
        out[split].append(chunk)
        if split == "train":
            summary.train += 1
        elif split == "valid":
            summary.valid += 1
        elif split == "test":
            summary.test += 1

    summary.missing_doc_ids = list(seen_missing.keys())
    return out, summary


def apply_manifest_to_chunks_iter(
    chunks: Iterable[Dict[str, Any]],
    manifest: SplitManifest,
    *,
    allow_missing: bool = False,
) -> Iterator[Tuple[str, Dict[str, Any]]]:
    """Streaming variant of :func:`apply_manifest_to_chunks`.

    Yields ``(split_name, chunk_dict)`` tuples so callers can write to
    file handles incrementally without holding the full result in memory.
    Chunks routed to ``"missing"`` are skipped only when ``allow_missing``
    is True; otherwise the function raises on first miss.
    """
    lookup = _doc_to_split_lookup(manifest)
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        doc_id = chunk.get("doc_id")
        if not isinstance(doc_id, str) or not doc_id:
            if allow_missing:
                continue
            raise ValueError("chunk missing 'doc_id'")
        split = lookup.get(doc_id)
        if split is None:
            if allow_missing:
                continue
            raise ValueError(
                f"chunk doc_id {doc_id!r} not present in manifest "
                f"(use allow_missing=True to skip)"
            )
        yield split, chunk


# ---------------------------------------------------------------- (de)serialize


def _grouping_from_dict(obj: Optional[Dict[str, Any]]) -> Optional[GroupingAudit]:
    if not isinstance(obj, dict):
        return None
    return GroupingAudit(
        total_docs=int(obj.get("total_docs", 0)),
        work_id_present_docs=int(obj.get("work_id_present_docs", 0)),
        work_id_missing_docs=int(obj.get("work_id_missing_docs", 0)),
        work_id_coverage_ratio=float(obj.get("work_id_coverage_ratio", 0.0)),
        fallback_group_count=int(obj.get("fallback_group_count", 0)),
        fallback_doc_ids_sample=list(obj.get("fallback_doc_ids_sample") or []),
        fallback_titles_sample=list(obj.get("fallback_titles_sample") or []),
    )


def manifest_from_dict(obj: Dict[str, Any]) -> SplitManifest:
    """Reconstruct a SplitManifest from a parsed JSON dict.

    Phase 3.5: ``grouping`` is read when present; legacy manifests without
    it round-trip with ``grouping=None``.
    """
    counts = obj.get("counts") or {}
    groups_counts = counts.get("groups") or {}
    docs_counts = counts.get("docs") or {}

    return SplitManifest(
        schema_version=obj.get("schema_version", SCHEMA_VERSION_SPLIT_MANIFEST),
        strategy=obj.get("strategy", DEFAULT_STRATEGY),
        seed=int(obj.get("seed", DEFAULT_SEED)),
        ratios={k: float(v) for k, v in (obj.get("ratios") or {}).items()},
        counts=SplitManifestCounts(
            groups=SplitCounts(
                train=int(groups_counts.get("train", 0)),
                valid=int(groups_counts.get("valid", 0)),
                test=int(groups_counts.get("test", 0)),
                total=int(groups_counts.get("total", 0)),
            ),
            docs=SplitCounts(
                train=int(docs_counts.get("train", 0)),
                valid=int(docs_counts.get("valid", 0)),
                test=int(docs_counts.get("test", 0)),
                total=int(docs_counts.get("total", 0)),
            ),
        ),
        groups={
            s: list(obj.get("groups", {}).get(s, [])) for s in SPLIT_NAMES
        },
        doc_ids={
            s: list(obj.get("doc_ids", {}).get(s, [])) for s in SPLIT_NAMES
        },
        doc_to_group=dict(obj.get("doc_to_group") or {}),
        fallback_group_count=int(obj.get("fallback_group_count", 0)),
        grouping=_grouping_from_dict(obj.get("grouping")),
        warnings=list(obj.get("warnings") or []),
    )


# ---------------------------------------------------------------- extend


def _scan_pages_for_extend(
    pages: Iterable[Dict[str, Any]],
    *,
    fallback_sample_size: int = DEFAULT_FALLBACK_SAMPLE_SIZE,
) -> Tuple[
    "OrderedDict[str, str]",
    "OrderedDict[str, List[str]]",
    set,
    int,
    int,
    List[str],
    List[str],
    List[str],
]:
    """Walk pages and bucket them into doc_to_group / group_to_docs.

    Returns ``(doc_to_group, group_to_docs, fallback_groups,
    work_id_present, work_id_missing, fallback_doc_id_samples,
    fallback_title_samples, warnings)``. Shared by ``build`` and
    ``extend`` so the two paths use identical bucket logic.
    """
    warnings: List[str] = []
    doc_to_group: "OrderedDict[str, str]" = OrderedDict()
    group_to_docs: "OrderedDict[str, List[str]]" = OrderedDict()
    fallback_groups: set = set()
    work_id_present = 0
    work_id_missing = 0
    fallback_doc_id_samples: List[str] = []
    fallback_title_samples: List[str] = []

    for page in pages:
        if not isinstance(page, dict):
            continue
        page_id = page.get("page_id")
        if not isinstance(page_id, str) or not page_id.strip():
            warnings.append("skipped page without page_id")
            continue
        page_id = page_id.strip()
        if page_id in doc_to_group:
            warnings.append(f"duplicate page_id {page_id!r}; later occurrence ignored")
            continue
        group_id, used_fallback = derive_group_id(page)
        if not group_id:
            warnings.append(f"skipped page {page_id!r}: no derivable group_id")
            continue
        doc_to_group[page_id] = group_id
        group_to_docs.setdefault(group_id, []).append(page_id)
        if used_fallback:
            fallback_groups.add(group_id)
            work_id_missing += 1
            if len(fallback_doc_id_samples) < fallback_sample_size:
                fallback_doc_id_samples.append(page_id)
                title = page.get("page_title")
                fallback_title_samples.append(
                    title if isinstance(title, str) else ""
                )
        else:
            work_id_present += 1

    return (
        doc_to_group,
        group_to_docs,
        fallback_groups,
        work_id_present,
        work_id_missing,
        fallback_doc_id_samples,
        fallback_title_samples,
        warnings,
    )


def _allocate_extension_split(
    *,
    current_counts: Dict[str, int],
    ratios: Dict[str, float],
) -> str:
    """Pick the split with the largest deficit relative to ratio targets.

    Tie-breaking: ``train`` > ``valid`` > ``test`` (the canonical order in
    :data:`SPLIT_NAMES`). The seeded shuffle that orders the new groups is
    applied *outside* this helper so the caller controls the randomness.
    """
    total = sum(current_counts.values()) + 1  # +1 for the group about to be added
    deficits: List[Tuple[str, float]] = []
    for s in SPLIT_NAMES:
        target = total * float(ratios.get(s, 0.0))
        deficits.append((s, target - current_counts[s]))
    # Largest deficit first; stable canonical order on ties.
    deficits.sort(key=lambda x: (-x[1], SPLIT_NAMES.index(x[0])))
    return deficits[0][0]


def extend_split_manifest(
    pages: Iterable[Dict[str, Any]],
    base_manifest: SplitManifest,
    *,
    seed: int = DEFAULT_SEED,
    drop_missing_docs: bool = False,
    max_fallback_ratio: Optional[float] = DEFAULT_MAX_FALLBACK_RATIO,
    fail_on_high_fallback: bool = False,
    fallback_sample_size: int = DEFAULT_FALLBACK_SAMPLE_SIZE,
) -> Tuple[SplitManifest, ExtensionAudit]:
    """Extend ``base_manifest`` with new groups discovered in ``pages``.

    Behaviour:
      * Groups already in the base manifest keep their split assignment
        (preserved) and pick up any new docs that the current input
        attached to them.
      * Groups only present in the current input are routed to whichever
        split has the largest ratio deficit; the new-group iteration
        order is a seeded deterministic shuffle.
      * Groups present in the base but missing from the current input are
        kept by default (with a warning); pass ``drop_missing_docs=True``
        to remove them, plus any base docs that are no longer in input.

    Returns ``(new_manifest, extension_audit)``. The audit is also
    available downstream via ``audit_manifest(..., extension=...)``.
    """
    (
        doc_to_group_input,
        group_to_docs_input,
        fallback_groups_input,
        work_id_present,
        work_id_missing,
        fallback_doc_id_samples,
        fallback_title_samples,
        warnings,
    ) = _scan_pages_for_extend(pages, fallback_sample_size=fallback_sample_size)

    if not doc_to_group_input:
        raise ValueError("no usable pages: input had 0 documents with page_id+group_id")

    total_input_docs = work_id_present + work_id_missing
    fallback_ratio = (
        (work_id_missing / total_input_docs) if total_input_docs > 0 else 0.0
    )
    if max_fallback_ratio is not None and fallback_ratio > max_fallback_ratio:
        msg = (
            f"work_id fallback ratio {fallback_ratio:.4f} exceeds threshold "
            f"{max_fallback_ratio:.4f} ({work_id_missing}/{total_input_docs} docs missing work_id)"
        )
        if fail_on_high_fallback:
            raise ValueError(msg)
        warnings.append(msg)

    # Index the base manifest by split.
    base_group_to_split: Dict[str, str] = {}
    for s in SPLIT_NAMES:
        for g in base_manifest.groups.get(s, []) or []:
            base_group_to_split[g] = s
    base_groups: set = set(base_group_to_split.keys())
    input_groups: set = set(group_to_docs_input.keys())
    new_groups: set = input_groups - base_groups
    preserved_groups: set = input_groups & base_groups
    missing_groups: set = base_groups - input_groups

    base_doc_to_split: Dict[str, str] = {}
    for s in SPLIT_NAMES:
        for d in base_manifest.doc_ids.get(s, []) or []:
            base_doc_to_split[d] = s
    base_doc_to_group: Dict[str, str] = dict(base_manifest.doc_to_group or {})

    new_groups_per_split: Dict[str, List[str]] = {s: [] for s in SPLIT_NAMES}
    new_docs_per_split: Dict[str, List[str]] = {s: [] for s in SPLIT_NAMES}
    new_doc_to_group: Dict[str, str] = {}
    dropped_doc_ids: List[str] = []
    dropped_group_ids: List[str] = []

    # 1. Preserved + missing groups: keep prior split (or drop) and
    #    carry forward their pre-existing doc assignments.
    for g, split in base_group_to_split.items():
        if g in missing_groups and drop_missing_docs:
            dropped_group_ids.append(g)
            continue
        new_groups_per_split[split].append(g)

    for d, split in base_doc_to_split.items():
        gid = base_doc_to_group.get(d)
        if drop_missing_docs:
            if d not in doc_to_group_input:
                dropped_doc_ids.append(d)
                continue
            if gid is None or gid in missing_groups:
                dropped_doc_ids.append(d)
                continue
        # Without drop_missing_docs we always keep base docs; their group
        # may also be missing — that base group is preserved above.
        new_docs_per_split[split].append(d)
        if gid is None:
            # Base manifest did not record a group for this doc; fall
            # back to the input mapping (or doc_id self-group).
            gid = doc_to_group_input.get(d, d)
        new_doc_to_group[d] = gid

    # 2. Preserved groups also accept brand-new docs (e.g. additional
    #    subpages under an existing work).
    for g in preserved_groups:
        split = base_group_to_split[g]
        for d in group_to_docs_input.get(g, []):
            if d in new_doc_to_group:
                continue
            new_docs_per_split[split].append(d)
            new_doc_to_group[d] = g

    # 3. Allocate new groups (deterministic seeded shuffle).
    ratios = base_manifest.ratios or {
        "train": DEFAULT_TRAIN_RATIO,
        "valid": DEFAULT_VALID_RATIO,
        "test": DEFAULT_TEST_RATIO,
    }
    new_groups_sorted = sorted(new_groups)
    rng = random.Random(seed)
    rng.shuffle(new_groups_sorted)

    added_groups_per_split: Dict[str, List[str]] = {s: [] for s in SPLIT_NAMES}
    for g in new_groups_sorted:
        current = {s: len(new_groups_per_split[s]) for s in SPLIT_NAMES}
        chosen = _allocate_extension_split(current_counts=current, ratios=ratios)
        new_groups_per_split[chosen].append(g)
        added_groups_per_split[chosen].append(g)
        for d in group_to_docs_input.get(g, []):
            new_docs_per_split[chosen].append(d)
            new_doc_to_group[d] = g

    # Defensive: deterministic, dedup-safe ordering.
    for s in SPLIT_NAMES:
        new_groups_per_split[s] = sorted(set(new_groups_per_split[s]))
        new_docs_per_split[s] = sorted(set(new_docs_per_split[s]))
        added_groups_per_split[s] = sorted(set(added_groups_per_split[s]))

    # Defensive leakage check — extension should never produce overlap.
    seen_docs: Dict[str, str] = {}
    for split, docs in (
        ("train", new_docs_per_split["train"]),
        ("valid", new_docs_per_split["valid"]),
        ("test", new_docs_per_split["test"]),
    ):
        for d in docs:
            prev = seen_docs.get(d)
            if prev is not None and prev != split:
                raise ValueError(
                    f"extend produced doc_id {d!r} in both {prev!r} and {split!r}"
                )
            seen_docs[d] = split

    # Warnings
    if missing_groups and not drop_missing_docs:
        warnings.append(
            f"{len(missing_groups)} group(s) present in base manifest are missing from input "
            f"(kept; pass --drop-missing-docs to remove them)"
        )
    if drop_missing_docs and (dropped_doc_ids or dropped_group_ids):
        warnings.append(
            f"dropped {len(dropped_doc_ids)} doc(s) and {len(dropped_group_ids)} group(s) "
            f"missing from input (--drop-missing-docs enabled)"
        )

    # Recompute fallback_group_count for the post-extension manifest.
    # Conservative: fold the input fallback set with any base fallback
    # signal (we can only flag preserved groups using the input scan;
    # missing-but-kept groups were not re-scanned so we trust the base
    # manifest's overall count as a lower bound on those).
    new_fallback_groups = set(fallback_groups_input)
    # Drop any fallback groups that were removed via --drop-missing-docs.
    new_fallback_groups -= set(dropped_group_ids)
    fallback_count = len(new_fallback_groups)
    # Track the share of remaining base fallback groups that we can no
    # longer re-confirm (missing-from-input). We keep them counted via
    # base_manifest.fallback_group_count when not dropped, to avoid
    # silently understating coverage gaps.
    if not drop_missing_docs and missing_groups:
        # We cannot tell which missing-from-input groups were fallback
        # without rescanning the original input; surface as a warning.
        warnings.append(
            "fallback_group_count reflects the current input only; "
            "groups missing-from-input are not re-scanned"
        )

    coverage_ratio = (
        (work_id_present / total_input_docs) if total_input_docs > 0 else 0.0
    )
    grouping_audit = GroupingAudit(
        total_docs=total_input_docs,
        work_id_present_docs=work_id_present,
        work_id_missing_docs=work_id_missing,
        work_id_coverage_ratio=coverage_ratio,
        fallback_group_count=fallback_count,
        fallback_doc_ids_sample=list(fallback_doc_id_samples),
        fallback_titles_sample=list(fallback_title_samples),
    )

    train_groups = new_groups_per_split["train"]
    valid_groups = new_groups_per_split["valid"]
    test_groups = new_groups_per_split["test"]
    train_docs = new_docs_per_split["train"]
    valid_docs = new_docs_per_split["valid"]
    test_docs = new_docs_per_split["test"]

    new_manifest = SplitManifest(
        schema_version=SCHEMA_VERSION_SPLIT_MANIFEST,
        strategy=DEFAULT_STRATEGY,
        seed=seed,
        ratios={
            "train": float(ratios.get("train", 0.0)),
            "valid": float(ratios.get("valid", 0.0)),
            "test": float(ratios.get("test", 0.0)),
        },
        counts=SplitManifestCounts(
            groups=SplitCounts(
                train=len(train_groups),
                valid=len(valid_groups),
                test=len(test_groups),
                total=len(train_groups) + len(valid_groups) + len(test_groups),
            ),
            docs=SplitCounts(
                train=len(train_docs),
                valid=len(valid_docs),
                test=len(test_docs),
                total=len(train_docs) + len(valid_docs) + len(test_docs),
            ),
        ),
        groups={"train": train_groups, "valid": valid_groups, "test": test_groups},
        doc_ids={"train": train_docs, "valid": valid_docs, "test": test_docs},
        doc_to_group=dict(new_doc_to_group),
        fallback_group_count=fallback_count,
        grouping=grouping_audit,
        warnings=warnings,
    )

    extension = ExtensionAudit(
        base_groups=len(base_groups),
        new_groups=len(new_groups),
        preserved_groups=len(preserved_groups),
        missing_groups_from_input=sorted(missing_groups),
        added_groups={s: list(added_groups_per_split[s]) for s in SPLIT_NAMES},
        dropped_doc_ids=sorted(dropped_doc_ids),
        dropped_group_ids=sorted(dropped_group_ids),
    )

    return new_manifest, extension
