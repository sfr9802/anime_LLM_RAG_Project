"""Tests for Phase 3.5 additions to the split_manifest module + CLIs.

Phase 3.5 is purely additive:
* :class:`GroupingAudit` — work_id coverage / fallback samples
* :class:`DistributionReport` — per-split page_type / section_type /
  chunks / group_size statistics
* :func:`extend_split_manifest` — adds new groups onto an existing
  manifest while preserving prior split assignments
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from eval.harness.split_manifest import (
    SCHEMA_VERSION_SPLIT_MANIFEST,
    SCHEMA_VERSION_SPLIT_REPORT,
    SPLIT_NAMES,
    DistributionReport,
    ExtensionAudit,
    GroupingAudit,
    SplitManifest,
    audit_manifest,
    build_split_manifest,
    extend_split_manifest,
    manifest_from_dict,
)
from scripts.audit_split_manifest import main as audit_main
from scripts.build_split_manifest import main as build_main
from scripts.extend_split_manifest import main as extend_main


# ---------------------------------------------------------------- fixtures


def _page(
    *,
    page_id: str,
    work_id: str = None,
    page_title: str = None,
    page_type: str = "work",
) -> Dict[str, Any]:
    out: Dict[str, Any] = {"page_id": page_id, "page_type": page_type}
    if work_id is not None:
        out["work_id"] = work_id
    if page_title is not None:
        out["page_title"] = page_title
    return out


def _ten_works(pages_per_work: int = 2) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    for i in range(10):
        for j in range(pages_per_work):
            pt = "work" if j == 0 else "character"
            pages.append(
                _page(
                    page_id=f"p{i}_{j}",
                    work_id=f"w{i}",
                    page_title=f"work_{i}_page_{j}",
                    page_type=pt,
                )
            )
    return pages


def _chunk(
    *,
    doc_id: str,
    chunk_id: str = None,
    section_type: str = "summary",
    payload: str = "x",
) -> Dict[str, Any]:
    return {
        "chunk_id": chunk_id or f"c_{doc_id}",
        "doc_id": doc_id,
        "section_type": section_type,
        "chunk_text": payload,
    }


def _write_pages_jsonl(path: Path, pages: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for p in pages:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def _write_chunks_jsonl(path: Path, chunks: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def _write_manifest_json(path: Path, manifest: SplitManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------- grouping audit


def test_grouping_audit_full_coverage():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42)
    assert m.grouping is not None
    assert m.grouping.total_docs == len(pages)
    assert m.grouping.work_id_present_docs == len(pages)
    assert m.grouping.work_id_missing_docs == 0
    assert m.grouping.work_id_coverage_ratio == pytest.approx(1.0)
    assert m.grouping.fallback_group_count == 0
    assert m.grouping.fallback_doc_ids_sample == []
    assert m.grouping.fallback_titles_sample == []


def test_grouping_audit_partial_fallback_collects_samples():
    pages: List[Dict[str, Any]] = []
    # 8 docs with work_id
    for i in range(8):
        pages.append(
            _page(page_id=f"p{i}", work_id=f"w{i}", page_title=f"title_{i}")
        )
    # 2 docs without work_id (forces fallback)
    pages.append(_page(page_id="orphan_1", page_title="고아 1"))
    pages.append(_page(page_id="orphan_2", page_title="고아 2"))

    m = build_split_manifest(pages, seed=42)
    assert m.grouping is not None
    assert m.grouping.total_docs == 10
    assert m.grouping.work_id_present_docs == 8
    assert m.grouping.work_id_missing_docs == 2
    assert m.grouping.work_id_coverage_ratio == pytest.approx(0.8)
    assert m.grouping.fallback_group_count == 2
    assert "orphan_1" in m.grouping.fallback_doc_ids_sample
    assert "orphan_2" in m.grouping.fallback_doc_ids_sample
    assert "고아 1" in m.grouping.fallback_titles_sample
    assert "고아 2" in m.grouping.fallback_titles_sample


def test_grouping_audit_warns_on_high_fallback_ratio():
    pages: List[Dict[str, Any]] = []
    for i in range(2):
        pages.append(_page(page_id=f"p{i}", work_id=f"w{i}"))
    for i in range(8):
        pages.append(_page(page_id=f"orphan_{i}"))  # 80% fallback

    m = build_split_manifest(pages, seed=42, max_fallback_ratio=0.05)
    # With max_fallback_ratio=0.05, ratio of 0.8 should be flagged.
    assert any("fallback ratio" in w.lower() for w in m.warnings)


def test_grouping_audit_fails_when_fail_flag_set():
    pages: List[Dict[str, Any]] = []
    for i in range(2):
        pages.append(_page(page_id=f"p{i}", work_id=f"w{i}"))
    for i in range(8):
        pages.append(_page(page_id=f"orphan_{i}"))

    with pytest.raises(ValueError) as excinfo:
        build_split_manifest(
            pages,
            seed=42,
            max_fallback_ratio=0.05,
            fail_on_high_fallback=True,
        )
    assert "fallback ratio" in str(excinfo.value).lower()


def test_grouping_audit_under_threshold_does_not_warn():
    pages: List[Dict[str, Any]] = []
    for i in range(99):
        pages.append(_page(page_id=f"p{i}", work_id=f"w{i}"))
    pages.append(_page(page_id="orphan_0"))  # 1% fallback

    m = build_split_manifest(pages, seed=42, max_fallback_ratio=0.05)
    # 1% < 5%, so no fallback-ratio warning
    assert not any("fallback ratio" in w.lower() for w in m.warnings)


def test_grouping_audit_threshold_disabled_by_default():
    pages: List[Dict[str, Any]] = []
    for i in range(2):
        pages.append(_page(page_id=f"p{i}", work_id=f"w{i}"))
    for i in range(8):
        pages.append(_page(page_id=f"orphan_{i}"))

    # No threshold passed → no fallback-ratio warning even at 80%
    m = build_split_manifest(pages, seed=42)
    assert not any("fallback ratio" in w.lower() for w in m.warnings)


def test_grouping_audit_round_trips_via_dict():
    pages: List[Dict[str, Any]] = [
        _page(page_id="p0", work_id="w0", page_title="t0"),
        _page(page_id="orphan_0", page_title="orphan"),
    ]
    m = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.5, test_ratio=0.0
    )
    obj = m.to_dict()
    m2 = manifest_from_dict(obj)
    assert m2.grouping is not None
    assert m2.grouping.total_docs == m.grouping.total_docs
    assert (
        m2.grouping.fallback_doc_ids_sample == m.grouping.fallback_doc_ids_sample
    )


def test_grouping_audit_in_split_report():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42)
    r = audit_manifest(m)
    assert r.grouping is not None
    assert r.grouping.work_id_coverage_ratio == pytest.approx(1.0)


# ---------------------------------------------------------------- distribution


def test_distribution_page_type_per_split():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(
        pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    r = audit_manifest(m, pages=pages)
    assert r.distribution is not None
    # Every doc has either page_type=work or page_type=character.
    total_typed = 0
    for s in SPLIT_NAMES:
        total_typed += sum(r.distribution.page_type[s].values())
    assert total_typed == len(pages)
    # Each split should have some coverage
    train_total = sum(r.distribution.page_type["train"].values())
    assert train_total > 0


def test_distribution_chunks_and_section_type():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(
        pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    chunks = []
    for p in pages:
        chunks.append(_chunk(doc_id=p["page_id"], section_type="summary"))
        chunks.append(_chunk(doc_id=p["page_id"], section_type="character"))
    r = audit_manifest(m, pages=pages, chunks=chunks)
    assert r.distribution is not None
    # Every chunk should be routed
    routed = sum(r.distribution.chunks[s] for s in SPLIT_NAMES)
    assert routed == len(chunks)
    # section_type counts must sum across splits to len(chunks)
    section_total = 0
    for s in SPLIT_NAMES:
        section_total += sum(r.distribution.section_type[s].values())
    assert section_total == len(chunks)


def test_distribution_omits_chunk_fields_when_no_chunks():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42)
    r = audit_manifest(m, pages=pages)  # no chunks
    assert r.distribution is not None
    assert r.distribution.chunks == {}
    assert r.distribution.section_type == {}
    # page_type still computed
    assert r.distribution.page_type
    # group_size avg_chunks_per_group should be 0 across splits
    for s in SPLIT_NAMES:
        gs = r.distribution.group_size[s]
        assert gs.avg_chunks_per_group == 0
        assert gs.max_chunks_per_group == 0


def test_distribution_group_size_per_split():
    # 5 works each with 3 docs → avg_docs_per_group = 3.0 in any non-empty split
    pages: List[Dict[str, Any]] = []
    for i in range(5):
        for j in range(3):
            pages.append(_page(page_id=f"p{i}_{j}", work_id=f"w{i}"))
    m = build_split_manifest(
        pages, seed=42, train_ratio=0.6, valid_ratio=0.2, test_ratio=0.2
    )
    r = audit_manifest(m, pages=pages)
    assert r.distribution is not None
    for s in SPLIT_NAMES:
        gs = r.distribution.group_size[s]
        if m.counts.groups.train if s == "train" else (
            m.counts.groups.valid if s == "valid" else m.counts.groups.test
        ):
            assert gs.avg_docs_per_group == pytest.approx(3.0)
            assert gs.max_docs_per_group == 3


def test_distribution_warns_when_valid_test_empty():
    # Tiny corpus: 2 works, 100/0/0 ratios → valid/test are empty
    pages = [_page(page_id=f"p{i}", work_id=f"w{i}") for i in range(2)]
    m = build_split_manifest(
        pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0
    )
    r = audit_manifest(m, pages=pages)
    # valid/test page_type should be empty
    assert r.distribution.page_type["valid"] == {}
    assert r.distribution.page_type["test"] == {}
    # And we should have surfaced a distribution warning for empty valid/test
    assert any("valid" in w and "0 pages" in w for w in r.warnings)
    assert any("test" in w and "0 pages" in w for w in r.warnings)


# ---------------------------------------------------------------- extend


def test_extend_preserves_existing_group_splits():
    base_pages = _ten_works(pages_per_work=2)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )

    # Add 3 brand new works, keep all base pages.
    extra = [_page(page_id=f"newp_{i}", work_id=f"new_w_{i}") for i in range(3)]
    new_pages = base_pages + extra
    extended, ext = extend_split_manifest(new_pages, base, seed=42)

    base_doc_to_split = {
        d: s for s in SPLIT_NAMES for d in base.doc_ids.get(s, [])
    }
    new_doc_to_split = {
        d: s for s in SPLIT_NAMES for d in extended.doc_ids.get(s, [])
    }
    # Every base doc must keep its split
    for d, s in base_doc_to_split.items():
        assert new_doc_to_split.get(d) == s, f"{d} was reassigned"


def test_extend_assigns_only_new_groups_and_reports_them():
    base_pages = _ten_works(pages_per_work=2)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    extra = [_page(page_id=f"newp_{i}", work_id=f"new_w_{i}") for i in range(3)]

    extended, ext = extend_split_manifest(base_pages + extra, base, seed=42)
    assert ext.base_groups == 10
    assert ext.preserved_groups == 10
    assert ext.new_groups == 3

    # added_groups should sum to 3 across splits
    added_total = sum(len(ext.added_groups[s]) for s in SPLIT_NAMES)
    assert added_total == 3
    added_set = set()
    for s in SPLIT_NAMES:
        added_set.update(ext.added_groups[s])
    assert added_set == {"new_w_0", "new_w_1", "new_w_2"}


def test_extend_is_deterministic_under_same_seed():
    base_pages = _ten_works(pages_per_work=2)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    extra = [_page(page_id=f"newp_{i}", work_id=f"new_w_{i}") for i in range(5)]
    new_pages = base_pages + extra

    e1, ext1 = extend_split_manifest(new_pages, base, seed=99)
    e2, ext2 = extend_split_manifest(new_pages, base, seed=99)
    assert e1.groups == e2.groups
    assert e1.doc_ids == e2.doc_ids
    assert e1.doc_to_group == e2.doc_to_group
    assert ext1.added_groups == ext2.added_groups


def test_extend_reports_missing_groups_from_input():
    base_pages = _ten_works(pages_per_work=2)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    # Drop work w9 from input; keep the rest, add a new work
    smaller = [p for p in base_pages if p["work_id"] != "w9"]
    smaller.append(_page(page_id="newp_0", work_id="new_w_0"))

    extended, ext = extend_split_manifest(smaller, base, seed=42)
    assert "w9" in ext.missing_groups_from_input
    # By default base docs are kept, including those from w9
    base_doc_to_split = {
        d: s for s in SPLIT_NAMES for d in base.doc_ids.get(s, [])
    }
    new_doc_to_split = {
        d: s for s in SPLIT_NAMES for d in extended.doc_ids.get(s, [])
    }
    for d in ("p9_0", "p9_1"):
        assert d in new_doc_to_split, f"{d} was silently dropped"
        assert new_doc_to_split[d] == base_doc_to_split[d]
    assert any("missing from input" in w for w in extended.warnings)


def test_extend_drops_missing_when_flag_set():
    base_pages = _ten_works(pages_per_work=2)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    smaller = [p for p in base_pages if p["work_id"] != "w9"]
    smaller.append(_page(page_id="newp_0", work_id="new_w_0"))

    extended, ext = extend_split_manifest(
        smaller, base, seed=42, drop_missing_docs=True
    )
    assert "w9" in ext.dropped_group_ids
    assert "p9_0" in ext.dropped_doc_ids
    assert "p9_1" in ext.dropped_doc_ids
    # And neither doc should be in any split
    for s in SPLIT_NAMES:
        assert "p9_0" not in extended.doc_ids[s]
        assert "p9_1" not in extended.doc_ids[s]
        assert "w9" not in extended.groups[s]


def test_extend_no_leakage_post_extension():
    base_pages = _ten_works(pages_per_work=3)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    extra = [_page(page_id=f"newp_{i}", work_id=f"new_w_{i}") for i in range(7)]
    extended, _ = extend_split_manifest(base_pages + extra, base, seed=11)

    r = audit_manifest(extended)
    assert r.leakage.doc_id_overlap == []
    assert r.leakage.group_id_overlap == []


def test_extend_picks_up_new_doc_under_existing_group():
    """If a re-crawl adds a new subpage to an existing work, the new doc
    inherits that work's split — never moves the work."""
    base_pages = _ten_works(pages_per_work=2)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    new_pages = base_pages + [_page(page_id="p0_2", work_id="w0")]
    extended, ext = extend_split_manifest(new_pages, base, seed=42)

    # find which split owns w0 in the base
    w0_split = None
    for s in SPLIT_NAMES:
        if "w0" in base.groups[s]:
            w0_split = s
            break
    assert w0_split is not None
    assert "p0_2" in extended.doc_ids[w0_split]
    # No extension allocation for w0 since it's preserved, not new.
    assert "w0" not in (
        ext.added_groups["train"] + ext.added_groups["valid"] + ext.added_groups["test"]
    )


# ---------------------------------------------------------------- CLI: build with new flags


def test_build_cli_chunks_input_enriches_distribution(tmp_path: Path):
    pages = _ten_works(pages_per_work=2)
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    out_path = tmp_path / "split_manifest.json"
    _write_pages_jsonl(pages_path, pages)
    chunks = []
    for p in pages:
        chunks.append(_chunk(doc_id=p["page_id"], section_type="summary"))
    _write_chunks_jsonl(chunks_path, chunks)

    rc = build_main(
        [
            "--input", str(pages_path),
            "--out", str(out_path),
            "--chunks", str(chunks_path),
            "--seed", "42",
            "--train-ratio", "0.7",
            "--valid-ratio", "0.2",
            "--test-ratio", "0.1",
        ]
    )
    assert rc == 0
    rep = json.loads(out_path.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert rep["distribution"] is not None
    chunks_by_split = rep["distribution"]["chunks"]
    assert sum(chunks_by_split.values()) == len(chunks)
    section_counts = rep["distribution"]["section_type"]
    # summary should appear in at least one split
    assert any("summary" in section_counts[s] for s in ("train", "valid", "test"))


def test_build_cli_max_fallback_ratio_warns(tmp_path: Path):
    pages: List[Dict[str, Any]] = []
    for i in range(2):
        pages.append(_page(page_id=f"p{i}", work_id=f"w{i}"))
    for i in range(8):
        pages.append(_page(page_id=f"orphan_{i}"))
    pages_path = tmp_path / "pages.jsonl"
    out_path = tmp_path / "m.json"
    _write_pages_jsonl(pages_path, pages)

    rc = build_main(
        [
            "--input", str(pages_path),
            "--out", str(out_path),
            "--train-ratio", "0.5",
            "--valid-ratio", "0.5",
            "--test-ratio", "0.0",
            "--max-fallback-ratio", "0.05",
        ]
    )
    assert rc == 0
    obj = json.loads(out_path.read_text(encoding="utf-8"))
    assert any("fallback ratio" in w.lower() for w in obj["warnings"])


def test_build_cli_fail_on_high_fallback(tmp_path: Path):
    pages: List[Dict[str, Any]] = []
    for i in range(2):
        pages.append(_page(page_id=f"p{i}", work_id=f"w{i}"))
    for i in range(8):
        pages.append(_page(page_id=f"orphan_{i}"))
    pages_path = tmp_path / "pages.jsonl"
    out_path = tmp_path / "m.json"
    _write_pages_jsonl(pages_path, pages)

    rc = build_main(
        [
            "--input", str(pages_path),
            "--out", str(out_path),
            "--train-ratio", "0.5",
            "--valid-ratio", "0.5",
            "--test-ratio", "0.0",
            "--max-fallback-ratio", "0.05",
            "--fail-on-high-fallback",
        ]
    )
    assert rc != 0


def test_build_cli_grouping_block_in_report(tmp_path: Path):
    pages = _ten_works(pages_per_work=2)
    pages_path = tmp_path / "pages.jsonl"
    out_path = tmp_path / "m.json"
    _write_pages_jsonl(pages_path, pages)
    rc = build_main(
        ["--input", str(pages_path), "--out", str(out_path)]
    )
    assert rc == 0
    rep = json.loads(out_path.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert rep["grouping"] is not None
    assert rep["grouping"]["work_id_coverage_ratio"] == pytest.approx(1.0)
    assert rep["grouping"]["work_id_present_docs"] == len(pages)


# ---------------------------------------------------------------- CLI: extend


def test_extend_cli_writes_extended_manifest_and_report(tmp_path: Path):
    base_pages = _ten_works(pages_per_work=2)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    base_manifest_path = tmp_path / "split_manifest.json"
    _write_manifest_json(base_manifest_path, base)

    new_pages = base_pages + [
        _page(page_id="newp_0", work_id="new_w_0"),
        _page(page_id="newp_1", work_id="new_w_1"),
    ]
    pages_path = tmp_path / "pages.jsonl"
    _write_pages_jsonl(pages_path, new_pages)
    out_path = tmp_path / "split_manifest.extended.json"

    rc = extend_main(
        [
            "--input", str(pages_path),
            "--base-manifest", str(base_manifest_path),
            "--out", str(out_path),
            "--seed", "42",
        ]
    )
    assert rc == 0
    assert out_path.exists()
    obj = json.loads(out_path.read_text(encoding="utf-8"))
    assert obj["schema_version"] == SCHEMA_VERSION_SPLIT_MANIFEST
    assert obj["counts"]["groups"]["total"] == 12

    report_path = out_path.with_suffix(".report.json")
    assert report_path.exists()
    rep = json.loads(report_path.read_text(encoding="utf-8"))
    assert rep["schema_version"] == SCHEMA_VERSION_SPLIT_REPORT
    assert rep["leakage"]["doc_id_overlap"] == []
    assert rep["leakage"]["group_id_overlap"] == []
    assert rep["extension"] is not None
    assert rep["extension"]["new_groups"] == 2
    assert rep["extension"]["preserved_groups"] == 10


def test_extend_cli_drop_missing_docs_flag(tmp_path: Path):
    base_pages = _ten_works(pages_per_work=2)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    base_manifest_path = tmp_path / "split_manifest.json"
    _write_manifest_json(base_manifest_path, base)

    smaller = [p for p in base_pages if p["work_id"] != "w9"]
    pages_path = tmp_path / "pages.jsonl"
    _write_pages_jsonl(pages_path, smaller)
    out_path = tmp_path / "split_manifest.extended.json"

    rc = extend_main(
        [
            "--input", str(pages_path),
            "--base-manifest", str(base_manifest_path),
            "--out", str(out_path),
            "--seed", "42",
            "--drop-missing-docs",
        ]
    )
    assert rc == 0
    rep = json.loads(out_path.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert "w9" in rep["extension"]["dropped_group_ids"]


def test_extend_cli_chunks_distribution(tmp_path: Path):
    base_pages = _ten_works(pages_per_work=2)
    base = build_split_manifest(
        base_pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    base_manifest_path = tmp_path / "split_manifest.json"
    _write_manifest_json(base_manifest_path, base)

    new_pages = base_pages + [_page(page_id="newp_0", work_id="new_w_0")]
    pages_path = tmp_path / "pages.jsonl"
    _write_pages_jsonl(pages_path, new_pages)
    chunks_path = tmp_path / "chunks.jsonl"
    chunks = [_chunk(doc_id=p["page_id"]) for p in new_pages]
    _write_chunks_jsonl(chunks_path, chunks)
    out_path = tmp_path / "split_manifest.extended.json"

    rc = extend_main(
        [
            "--input", str(pages_path),
            "--base-manifest", str(base_manifest_path),
            "--out", str(out_path),
            "--chunks", str(chunks_path),
            "--seed", "42",
        ]
    )
    assert rc == 0
    rep = json.loads(out_path.with_suffix(".report.json").read_text(encoding="utf-8"))
    assert rep["distribution"] is not None
    routed = sum(rep["distribution"]["chunks"].values())
    assert routed == len(chunks)


# ---------------------------------------------------------------- CLI: audit


def test_audit_cli_writes_full_report(tmp_path: Path):
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(
        pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1
    )
    pages_path = tmp_path / "pages.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    chunks_path = tmp_path / "chunks.jsonl"
    out_path = tmp_path / "report.json"
    _write_pages_jsonl(pages_path, pages)
    _write_manifest_json(manifest_path, m)
    _write_chunks_jsonl(chunks_path, [_chunk(doc_id=p["page_id"]) for p in pages])

    rc = audit_main(
        [
            "--manifest", str(manifest_path),
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--out", str(out_path),
        ]
    )
    assert rc == 0
    rep = json.loads(out_path.read_text(encoding="utf-8"))
    assert rep["schema_version"] == SCHEMA_VERSION_SPLIT_REPORT
    assert rep["grouping"] is not None
    assert rep["distribution"] is not None
    assert sum(rep["distribution"]["chunks"].values()) == len(pages)
