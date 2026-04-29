"""Tests for the Phase 5 pre-recrawl audit harness.

Covers the four audit blocks (pages, chunks, manifest, sft), the
warning-trigger thresholds, the markdown renderer, and the CLI.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from eval.harness.crawl_v4_audit import (
    AuditThresholds,
    SCHEMA_VERSION_CRAWL_AUDIT,
    audit_chunks,
    audit_manifest_block,
    audit_pages,
    audit_sft_block,
    render_markdown,
    run_full_audit,
)
from eval.harness.split_manifest import build_split_manifest
from scripts.audit_crawl_v4 import main as audit_main


# ---------------------------------------------------------------- fixtures


def _page(
    *,
    page_id: str,
    work_id: str = "wA",
    work_title: str = "작품A",
    page_title: str = None,
    page_type: str = "work",
    aliases: List[str] = None,
    fetched_at: str = "2026-01-01T00:00:00",
    canonical_url: str = None,
    section_types: List[str] = None,
) -> Dict[str, Any]:
    sections: List[Dict[str, Any]] = []
    for i, st in enumerate(section_types or ["summary"]):
        sections.append(
            {
                "section_id": f"sid_{page_id}_{i}",
                "section_key": f"sk_{page_id}_{i}",
                "heading_path": ["본문"],
                "depth": 1,
                "order": i,
                "text": "이 작품은 충분히 긴 본문 텍스트를 가진 섹션이다. 메인 주인공이 등장한다.",
                "raw_text": "이 작품은 충분히 긴 본문 텍스트를 가진 섹션이다. 메인 주인공이 등장한다.",
                "clean_text": "이 작품은 충분히 긴 본문 텍스트를 가진 섹션이다. 메인 주인공이 등장한다.",
                "section_type": st,
                "links": [],
                "quality": {
                    "text_length": 120,
                    "noise_score": 0.0,
                    "is_stub": False,
                    "has_spoiler": False,
                    "is_table_like": False,
                    "is_list_like": False,
                },
            }
        )
    return {
        "schema_version": "namu_anime_v4_page",
        "page_id": page_id,
        "work_id": work_id,
        "work_title": work_title,
        "page_title": page_title or work_title,
        "page_type": page_type,
        "relation": "main" if page_type == "work" else page_type,
        "canonical_url": canonical_url or f"https://namu.wiki/w/{page_id}",
        "aliases": aliases or [],
        "source": {
            "site": "namu.wiki",
            "fetched_at": fetched_at,
            "revision_time": None,
        },
        "sections": sections,
    }


def _chunk(
    *,
    doc_id: str,
    chunk_id: str = None,
    section_id: str = None,
    section_key: str = None,
    section_type: str = "summary",
    text_length: int = 200,
    chunk_text: str = None,
    is_stub: bool = False,
    is_table_like: bool = False,
    is_list_like: bool = False,
) -> Dict[str, Any]:
    text = chunk_text or ("본문 텍스트가 충분히 긴 형태로 채워진다. 두 번째 문장. 세 번째 문장.")
    return {
        "schema_version": "namu_anime_v4_rag_chunk",
        "chunk_id": chunk_id or f"c_{doc_id}_{section_type}",
        "doc_id": doc_id,
        "title": doc_id,
        "section_id": section_id or f"sid_{doc_id}_{section_type}",
        "section_key": section_key or f"sk_{doc_id}_{section_type}",
        "section_type": section_type,
        "chunk_text": text,
        "embedding_text": text,
        "metadata": {
            "source_url": None,
            "crawl_version": "v4",
            "has_spoiler": False,
            "text_length": text_length,
            "noise_score": 0.0,
            "is_stub": is_stub,
            "is_table_like": is_table_like,
            "is_list_like": is_list_like,
        },
    }


def _write_jsonl(path: Path, items: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- pages


def test_audit_pages_basic_counts():
    pages = [
        _page(page_id="p0", work_id="w0", work_title="작품_0"),
        _page(page_id="p1", work_id="w1", work_title="작품_1"),
    ]
    audit, warnings = audit_pages(pages, AuditThresholds())
    assert audit.total_pages == 2
    assert audit.page_type_distribution.get("work") == 2
    assert audit.missing_work_title == 0
    assert audit.duplicate_page_ids == []


def test_audit_pages_detects_duplicate_page_ids():
    pages = [
        _page(page_id="dup", work_id="w0", work_title="A"),
        _page(page_id="dup", work_id="w1", work_title="B"),
    ]
    audit, warnings = audit_pages(pages, AuditThresholds())
    assert "dup" in audit.duplicate_page_ids
    assert any("duplicated page_id" in w for w in warnings)


def test_audit_pages_detects_missing_work_title():
    pages = [
        _page(page_id="p0", work_id="w0", work_title=""),
        _page(page_id="p1", work_id="w1", work_title=""),
        _page(page_id="p2", work_id="w2", work_title="작품"),
    ]
    audit, warnings = audit_pages(pages, AuditThresholds(work_title_missing_warn_ratio=0.1))
    assert audit.missing_work_title == 2
    assert any("work_title missing" in w for w in warnings)


def test_audit_pages_detects_missing_fetched_at():
    pages = [
        _page(page_id=f"p{i}", work_id=f"w{i}", fetched_at="") for i in range(3)
    ]
    audit, warnings = audit_pages(pages, AuditThresholds(fetched_at_missing_warn_ratio=0.1))
    assert audit.missing_fetched_at == 3
    assert any("fetched_at" in w for w in warnings)


def test_audit_pages_section_type_distribution():
    pages = [
        _page(page_id="p0", section_types=["summary", "character"]),
        _page(page_id="p1", section_types=["setting", "summary"]),
    ]
    audit, _ = audit_pages(pages, AuditThresholds())
    assert audit.section_type_distribution.get("summary") == 2
    assert audit.section_type_distribution.get("character") == 1
    assert audit.section_type_distribution.get("setting") == 1
    assert audit.section_count_stats.count == 2


def test_audit_pages_unsupported_section_type_warning():
    pages = [
        _page(page_id="p0", section_types=["other", "other"]),
        _page(page_id="p1", section_types=["other", "summary"]),
    ]
    audit, warnings = audit_pages(
        pages, AuditThresholds(unsupported_section_type_warn_ratio=0.5)
    )
    assert audit.other_section_type_count == 3
    assert audit.unsupported_section_type_ratio == pytest.approx(0.75)
    assert any("unsupported" in w.lower() or "other section_type" in w.lower() for w in warnings)


# ---------------------------------------------------------------- chunks


def test_audit_chunks_basic_counts():
    chunks = [
        _chunk(doc_id="p0", chunk_id="c0"),
        _chunk(doc_id="p1", chunk_id="c1"),
    ]
    audit, warnings = audit_chunks(chunks, AuditThresholds())
    assert audit.total_chunks == 2
    assert audit.duplicate_chunk_ids == []
    assert audit.text_length_stats.count == 2


def test_audit_chunks_detects_duplicate_chunk_ids():
    chunks = [
        _chunk(doc_id="p0", chunk_id="dup"),
        _chunk(doc_id="p1", chunk_id="dup"),
    ]
    audit, warnings = audit_chunks(chunks, AuditThresholds())
    assert "dup" in audit.duplicate_chunk_ids
    assert any("duplicated chunk_id" in w for w in warnings)


def test_audit_chunks_too_short_warning():
    chunks = [
        _chunk(
            doc_id="p0",
            chunk_id=f"c{i}",
            chunk_text="짧",
            text_length=1,
        )
        for i in range(5)
    ]
    audit, warnings = audit_chunks(
        chunks, AuditThresholds(too_short_chars=10, short_chunk_warn_ratio=0.5)
    )
    assert audit.too_short_count == 5
    assert any("too-short" in w for w in warnings)


def test_audit_chunks_top_work_skew():
    # 8 chunks for w0, 1 chunk for w1, 1 chunk for w2 → w0 owns 80%
    chunks = []
    for i in range(8):
        chunks.append(_chunk(doc_id="p_dom", chunk_id=f"c_dom_{i}"))
    chunks.append(_chunk(doc_id="p_a", chunk_id="c_a"))
    chunks.append(_chunk(doc_id="p_b", chunk_id="c_b"))
    doc_to_work = {
        "p_dom": ("w_dom", "도미넌트작품"),
        "p_a": ("w_a", "A"),
        "p_b": ("w_b", "B"),
    }
    audit, warnings = audit_chunks(
        chunks,
        AuditThresholds(work_skew_warn_ratio=0.3),
        doc_to_work=doc_to_work,
    )
    assert audit.top_work_skew[0].work_id == "w_dom"
    assert audit.top_work_skew[0].chunk_count == 8
    assert audit.top_work_skew[0].ratio == pytest.approx(0.8)
    assert any("도미넌트" in w or "skewed" in w for w in warnings)


def test_audit_chunks_quality_flag_ratios():
    chunks = [
        _chunk(doc_id="p0", chunk_id="c0", is_stub=True),
        _chunk(doc_id="p1", chunk_id="c1", is_table_like=True),
        _chunk(doc_id="p2", chunk_id="c2", is_list_like=True),
        _chunk(doc_id="p3", chunk_id="c3"),
    ]
    audit, _ = audit_chunks(chunks, AuditThresholds())
    assert audit.is_stub_count == 1
    assert audit.is_table_like_count == 1
    assert audit.is_list_like_count == 1
    assert audit.is_stub_ratio == pytest.approx(0.25)


# ---------------------------------------------------------------- manifest


def test_audit_manifest_basic_counts():
    pages = [
        _page(page_id=f"p{i}", work_id=f"w{i}", work_title=f"작품{i}")
        for i in range(6)
    ]
    chunks = [_chunk(doc_id=f"p{i}", chunk_id=f"c{i}") for i in range(6)]
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    audit, warnings = audit_manifest_block(manifest, pages, chunks, AuditThresholds())
    assert audit.split_doc_counts["train"] + audit.split_doc_counts["valid"] + audit.split_doc_counts["test"] == 6
    assert sum(audit.split_chunk_counts.values()) == 6
    assert audit.leaked_doc_ids == []


def test_audit_manifest_detects_chunks_outside_manifest():
    pages = [_page(page_id="p0", work_id="w0", work_title="A")]
    chunks = [
        _chunk(doc_id="p0", chunk_id="c0"),
        _chunk(doc_id="ghost", chunk_id="c_ghost"),
    ]
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0
    )
    audit, warnings = audit_manifest_block(manifest, pages, chunks, AuditThresholds())
    assert audit.chunks_outside_manifest == 1
    assert any("doc_ids absent" in w for w in warnings)


def test_audit_manifest_section_type_split_distribution():
    pages = [
        _page(
            page_id=f"p{i}",
            work_id=f"w{i}",
            work_title=f"작품{i}",
            section_types=["summary", "character"],
        )
        for i in range(4)
    ]
    chunks = [_chunk(doc_id=p["page_id"]) for p in pages]
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    audit, _ = audit_manifest_block(manifest, pages, chunks, AuditThresholds())
    # Each split's section_type distribution sums to (#docs in split * 2)
    for s, dist in audit.split_section_type_distribution.items():
        if audit.split_doc_counts[s] > 0:
            assert sum(dist.values()) == audit.split_doc_counts[s] * 2


def test_audit_manifest_detects_split_section_type_gap():
    """If valid/test docs only have section_types that train lacks (or vice versa),
    flag a coverage gap."""
    pages = [
        # all docs have a 'character' section
        _page(page_id="p0", work_id="w0", work_title="A", section_types=["character"]),
        _page(page_id="p1", work_id="w1", work_title="B", section_types=["character"]),
        _page(page_id="p2", work_id="w2", work_title="C", section_types=["character"]),
        _page(page_id="p3", work_id="w3", work_title="D", section_types=["character"]),
        # plus one summary-only page that splits into the test bucket
        _page(page_id="p4", work_id="w4", work_title="E", section_types=["summary"]),
    ]
    chunks = [_chunk(doc_id=p["page_id"]) for p in pages]
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.6, valid_ratio=0.2, test_ratio=0.2
    )
    audit, warnings = audit_manifest_block(manifest, pages, chunks, AuditThresholds())
    # at least one split should be missing some section type
    union = set()
    for s in ("train", "valid", "test"):
        union.update(audit.split_section_type_distribution[s].keys())
    has_gap = any(
        bool(set(union) - set(audit.split_section_type_distribution[s].keys()))
        for s in ("valid", "test")
    )
    assert has_gap == bool(audit.splits_missing_section_types)


def test_audit_manifest_detects_doc_leakage():
    # Hand-craft a leaky manifest by injecting a doc into both train and valid
    pages = [
        _page(page_id=f"p{i}", work_id=f"w{i}", work_title=f"A{i}") for i in range(4)
    ]
    chunks = [_chunk(doc_id=p["page_id"]) for p in pages]
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    leaker = manifest.doc_ids["train"][0]
    manifest.doc_ids["valid"] = list(manifest.doc_ids["valid"]) + [leaker]
    audit, warnings = audit_manifest_block(manifest, pages, chunks, AuditThresholds())
    assert leaker in audit.leaked_doc_ids
    assert any("leak across splits" in w for w in warnings)


# ---------------------------------------------------------------- sft


def test_audit_sft_query_rewrite_too_low_warning():
    page_audit_stub = type("PA", (), {"total_pages": 100})()
    sft_report = {
        "counts": {
            "query_rewrite": {"train": 1, "valid": 0, "test": 0},
            "context_answer": {"train": 100, "valid": 10, "test": 10},
        },
        "skipped": {},
        "section_type_distribution": {
            "query_rewrite": {},
            "context_answer": {
                "train": {"summary": 50, "character": 50},
                "valid": {},
                "test": {},
            },
        },
    }
    audit, warnings = audit_sft_block(
        sft_report, page_audit_stub, AuditThresholds(query_rewrite_min_per_page=0.2)
    )
    assert audit.query_rewrite_to_pages_ratio < 0.2
    assert any("query_rewrite total" in w for w in warnings)


def test_audit_sft_context_answer_skew_warning():
    page_audit_stub = type("PA", (), {"total_pages": 10})()
    sft_report = {
        "counts": {
            "query_rewrite": {"train": 5, "valid": 1, "test": 1},
            "context_answer": {"train": 80, "valid": 10, "test": 10},
        },
        "skipped": {},
        "section_type_distribution": {
            "query_rewrite": {},
            "context_answer": {
                "train": {"summary": 80},
                "valid": {"summary": 10},
                "test": {"summary": 10},
            },
        },
    }
    audit, warnings = audit_sft_block(
        sft_report,
        page_audit_stub,
        AuditThresholds(context_answer_skew_warn_ratio=0.7),
    )
    assert audit.context_answer_top_section_type == "summary"
    assert audit.context_answer_top_section_ratio == pytest.approx(1.0)
    assert any("context_answer top section_type" in w for w in warnings)


# ---------------------------------------------------------------- run_full_audit


def test_run_full_audit_no_warnings_on_clean_corpus():
    pages = [
        _page(
            page_id=f"p{i}",
            work_id=f"w{i}",
            work_title=f"작품{i}",
            aliases=[f"alias_{i}"],
            section_types=["summary", "character", "setting"],
        )
        for i in range(8)
    ]
    chunks = []
    for p in pages:
        for st in ("summary", "character", "setting"):
            chunks.append(_chunk(doc_id=p["page_id"], chunk_id=f"c_{p['page_id']}_{st}", section_type=st))
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    report = run_full_audit(pages=pages, chunks=chunks, manifest=manifest)
    assert report.schema_version == SCHEMA_VERSION_CRAWL_AUDIT
    assert report.pages.total_pages == 8
    assert report.chunks.total_chunks == 24
    # On a clean corpus, no leakage / no duplicate warnings
    assert all("leak" not in w for w in report.warnings)
    assert all("duplicated" not in w for w in report.warnings)


def test_render_markdown_contains_each_section():
    pages = [_page(page_id="p0", work_id="w0", work_title="A", aliases=["alias"])]
    chunks = [_chunk(doc_id="p0", chunk_id="c0")]
    report = run_full_audit(pages=pages, chunks=chunks)
    md = render_markdown(report)
    assert "# Crawl V4 Audit Report" in md
    assert "## Pages" in md
    assert "## Chunks" in md
    assert "## Warnings" in md
    # Manifest/SFT sections only when those inputs exist
    assert "## Manifest" not in md
    assert "## SFT" not in md


def test_render_markdown_includes_manifest_and_sft_when_provided():
    pages = [
        _page(page_id=f"p{i}", work_id=f"w{i}", work_title=f"A{i}") for i in range(4)
    ]
    chunks = [_chunk(doc_id=p["page_id"]) for p in pages]
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    sft_report = {
        "counts": {
            "query_rewrite": {"train": 4, "valid": 1, "test": 1},
            "context_answer": {"train": 4, "valid": 1, "test": 1},
        },
        "skipped": {"low_quality": 0, "too_short": 0, "missing_manifest": 0,
                    "missing_evidence": 0, "unsupported_section_type": 0},
        "section_type_distribution": {
            "query_rewrite": {"train": {"summary": 4}, "valid": {"summary": 1}, "test": {"summary": 1}},
            "context_answer": {"train": {"summary": 4}, "valid": {"summary": 1}, "test": {"summary": 1}},
        },
    }
    report = run_full_audit(
        pages=pages, chunks=chunks, manifest=manifest, sft_report=sft_report
    )
    md = render_markdown(report)
    assert "## Manifest" in md
    assert "## SFT" in md


# ---------------------------------------------------------------- CLI


def test_cli_writes_json_and_markdown(tmp_path: Path):
    pages = [
        _page(page_id=f"p{i}", work_id=f"w{i}", work_title=f"작품{i}", aliases=[f"a{i}"])
        for i in range(4)
    ]
    chunks = [_chunk(doc_id=p["page_id"]) for p in pages]
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "audit"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    manifest_path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False), encoding="utf-8"
    )

    rc = audit_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc == 0
    json_path = out_dir / "crawl_v4_audit_report.json"
    md_path = out_dir / "crawl_v4_audit_report.md"
    assert json_path.exists()
    assert md_path.exists()
    obj = json.loads(json_path.read_text(encoding="utf-8"))
    assert obj["schema_version"] == SCHEMA_VERSION_CRAWL_AUDIT
    assert "pages" in obj
    assert "chunks" in obj
    assert obj["manifest"] is not None


def test_cli_no_markdown_flag(tmp_path: Path):
    pages = [_page(page_id="p0", work_id="w0", work_title="A")]
    chunks = [_chunk(doc_id="p0", chunk_id="c0")]
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    out_dir = tmp_path / "audit"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    rc = audit_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--out-dir", str(out_dir),
            "--no-markdown",
        ]
    )
    assert rc == 0
    assert (out_dir / "crawl_v4_audit_report.json").exists()
    assert not (out_dir / "crawl_v4_audit_report.md").exists()


def test_cli_with_sft_report(tmp_path: Path):
    pages = [
        _page(page_id=f"p{i}", work_id=f"w{i}", work_title=f"A{i}") for i in range(4)
    ]
    chunks = [_chunk(doc_id=p["page_id"]) for p in pages]
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    sft_path = tmp_path / "sft_report.json"
    out_dir = tmp_path / "audit"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    sft_path.write_text(
        json.dumps(
            {
                "counts": {
                    "query_rewrite": {"train": 4, "valid": 1, "test": 1},
                    "context_answer": {"train": 4, "valid": 1, "test": 1},
                },
                "skipped": {
                    "low_quality": 0, "too_short": 0,
                    "missing_manifest": 0, "missing_evidence": 0,
                    "unsupported_section_type": 0,
                },
                "section_type_distribution": {
                    "query_rewrite": {},
                    "context_answer": {
                        "train": {"summary": 4},
                        "valid": {"summary": 1},
                        "test": {"summary": 1},
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    rc = audit_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--sft-report", str(sft_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc == 0
    obj = json.loads((out_dir / "crawl_v4_audit_report.json").read_text(encoding="utf-8"))
    assert obj["sft"] is not None
    assert obj["sft"]["query_rewrite_counts"]["train"] == 4


def test_cli_rejects_missing_inputs(tmp_path: Path):
    rc = audit_main(
        [
            "--pages", str(tmp_path / "nope.jsonl"),
            "--chunks", str(tmp_path / "nope2.jsonl"),
            "--out-dir", str(tmp_path / "out"),
        ]
    )
    assert rc != 0
