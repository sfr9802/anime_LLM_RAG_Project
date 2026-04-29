"""Phase 5.1 — section heading preservation + --fail-on-warning tests.

These tests live in their own file (rather than extending
``tests/test_crawl_v4_audit.py``) so the original Phase 5 audit tests
keep their tightly-scoped fixtures unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from eval.harness.crawl_v4_audit import (
    AuditThresholds,
    audit_chunks,
    audit_pages,
    render_markdown,
    run_full_audit,
)
from scripts.audit_crawl_v4 import main as audit_main


# ---------------------------------------------------------------- fixtures


def _page(
    *,
    page_id: str,
    work_id: str = "wA",
    work_title: str = "작품A",
    page_type: str = "work",
    sections: List[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    sections = sections or []
    return {
        "schema_version": "namu_anime_v4_page",
        "page_id": page_id,
        "work_id": work_id,
        "work_title": work_title,
        "page_title": work_title,
        "page_type": page_type,
        "relation": "main" if page_type == "work" else page_type,
        "canonical_url": f"https://namu.wiki/w/{page_id}",
        "aliases": ["alias_" + page_id],
        "source": {
            "site": "namu.wiki",
            "fetched_at": "2026-04-01T00:00:00",
            "revision_time": None,
        },
        "sections": sections,
    }


def _section(
    *,
    page_id: str,
    order: int,
    heading_path: List[str],
    depth: int = 1,
    section_type: str = "summary",
) -> Dict[str, Any]:
    return {
        "section_id": f"sid_{page_id}_{order}",
        "section_key": f"sk_{page_id}_{order}",
        "heading_path": heading_path,
        "depth": depth,
        "order": order,
        "text": "이 섹션은 충분한 길이의 본문을 포함한다. 두 번째 문장.",
        "raw_text": "이 섹션은 충분한 길이의 본문을 포함한다. 두 번째 문장.",
        "clean_text": "이 섹션은 충분한 길이의 본문을 포함한다. 두 번째 문장.",
        "section_type": section_type,
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


def _chunk(
    *,
    doc_id: str,
    chunk_id: str,
    section_path: List[str] | None,
    section_type: str = "summary",
) -> Dict[str, Any]:
    return {
        "schema_version": "namu_anime_v4_rag_chunk",
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "title": doc_id,
        "section_id": f"sid_{doc_id}",
        "section_key": f"sk_{doc_id}",
        "section_path": section_path,
        "section_type": section_type,
        "chunk_text": "본문 텍스트가 충분히 길게 채워진다. 두 번째 문장. 세 번째 문장.",
        "embedding_text": "...",
        "metadata": {
            "source_url": None,
            "crawl_version": "v4",
            "has_spoiler": False,
            "text_length": 120,
            "noise_score": 0.0,
            "is_stub": False,
            "is_table_like": False,
            "is_list_like": False,
        },
    }


def _write_jsonl(path: Path, items: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- page metrics


def test_page_audit_collapsed_to_single_summary_emits_warnings():
    """Every page has exactly one ``["본문"]`` section (the light-crawl
    failure mode). Phase 5.1 should fire mean-section, summary-skew,
    generic-title, and depth warnings."""
    pages = [
        _page(
            page_id=f"p{i}",
            sections=[
                _section(page_id=f"p{i}", order=0, heading_path=["본문"], depth=1)
            ],
        )
        for i in range(5)
    ]
    audit, warnings = audit_pages(pages, AuditThresholds())
    assert audit.section_count_stats.mean == pytest.approx(1.0)
    assert audit.sections_with_generic_title_count == 5
    assert audit.section_depth_distribution == {"1": 5}
    msgs = " | ".join(warnings)
    assert "mean section_count" in msgs
    assert "summary" in msgs and "owns" in msgs
    assert "generic" in msgs.lower()
    assert "section depth" in msgs


def test_page_audit_blank_heading_path_counted():
    pages = [
        _page(
            page_id="p0",
            sections=[
                _section(page_id="p0", order=0, heading_path=[]),
                _section(page_id="p0", order=1, heading_path=["설정", "기본"], depth=2),
            ],
        )
    ]
    audit, _ = audit_pages(pages, AuditThresholds())
    assert audit.sections_with_blank_title_count == 1
    assert "__blank__" in audit.section_title_distribution


def test_page_audit_blank_warning_threshold():
    """Many sections with blank heading paths -> blank warning fires."""
    pages = [
        _page(
            page_id=f"p{i}",
            sections=[
                _section(page_id=f"p{i}", order=0, heading_path=[]),
                _section(page_id=f"p{i}", order=1, heading_path=[""]),
            ],
        )
        for i in range(3)
    ]
    audit, warnings = audit_pages(
        pages, AuditThresholds(blank_section_title_warn_ratio=0.3)
    )
    assert audit.sections_with_blank_title_count == 6
    assert any("blank heading_path" in w for w in warnings)


def test_page_audit_clean_corpus_no_phase51_warnings():
    """A page with multiple non-generic sections at multiple depths
    should not trigger any of the Phase 5.1 warnings."""
    pages = []
    for i in range(4):
        pid = f"p{i}"
        pages.append(
            _page(
                page_id=pid,
                sections=[
                    _section(
                        page_id=pid,
                        order=0,
                        heading_path=["줄거리", "1기"],
                        depth=2,
                        section_type="synopsis",
                    ),
                    _section(
                        page_id=pid,
                        order=1,
                        heading_path=["등장인물", "주인공"],
                        depth=2,
                        section_type="character",
                    ),
                    _section(
                        page_id=pid,
                        order=2,
                        heading_path=["설정"],
                        depth=1,
                        section_type="setting",
                    ),
                ],
            )
        )
    audit, warnings = audit_pages(pages, AuditThresholds())
    assert audit.section_count_stats.mean == pytest.approx(3.0)
    msgs = " | ".join(warnings)
    assert "mean section_count" not in msgs
    assert "summary' owns" not in msgs
    assert "generic" not in msgs.lower()
    assert "section depth" not in msgs


def test_page_audit_top_section_titles_truncated_to_top_n():
    sections_over_top_n: List[Dict[str, Any]] = []
    for i in range(20):
        sections_over_top_n.append(
            _section(
                page_id="p0",
                order=i,
                heading_path=[f"제목_{i % 12}"],
                depth=1,
                section_type="summary",
            )
        )
    pages = [_page(page_id="p0", sections=sections_over_top_n)]
    audit, _ = audit_pages(
        pages, AuditThresholds(section_title_top_n=5)
    )
    assert len(audit.top_section_titles) == 5


# ---------------------------------------------------------------- chunk metrics


def test_chunk_audit_blank_section_title_counted():
    chunks = [
        _chunk(doc_id="p0", chunk_id="c0", section_path=[]),
        _chunk(doc_id="p0", chunk_id="c1", section_path=None),
        _chunk(doc_id="p0", chunk_id="c2", section_path=["줄거리"]),
    ]
    audit, warnings = audit_chunks(
        chunks,
        AuditThresholds(blank_section_title_warn_ratio=0.3),
    )
    assert audit.chunks_with_blank_section_title_count == 2
    assert any("blank section_path" in w for w in warnings)


def test_chunk_audit_top_section_titles_present():
    chunks = []
    # 5 chunks under "줄거리", 3 under "설정", 1 under "등장인물"
    for i in range(5):
        chunks.append(
            _chunk(doc_id="p0", chunk_id=f"c_p_{i}", section_path=["줄거리"])
        )
    for i in range(3):
        chunks.append(
            _chunk(doc_id="p0", chunk_id=f"c_s_{i}", section_path=["설정"])
        )
    chunks.append(
        _chunk(doc_id="p0", chunk_id="c_e_0", section_path=["등장인물"])
    )
    audit, _ = audit_chunks(chunks, AuditThresholds(section_title_top_n=2))
    assert len(audit.chunks_by_section_title_top_n) == 2
    titles = [e.section_title for e in audit.chunks_by_section_title_top_n]
    assert titles[0] == "줄거리"
    assert audit.chunks_by_section_title_top_n[0].count == 5


# ---------------------------------------------------------------- markdown


def test_render_markdown_includes_phase51_blocks():
    pages = [
        _page(
            page_id="p0",
            sections=[
                _section(page_id="p0", order=0, heading_path=["줄거리"], depth=1)
            ],
        )
    ]
    chunks = [
        _chunk(doc_id="p0", chunk_id="c0", section_path=["줄거리"]),
    ]
    report = run_full_audit(pages=pages, chunks=chunks)
    md = render_markdown(report)
    assert "section_depth distribution" in md
    assert "top section titles" in md
    assert "chunks_with_blank_section_title" in md
    assert "chunks by section_title" in md


# ---------------------------------------------------------------- CLI fail-on-warning


def test_cli_fail_on_warning_returns_nonzero_when_warnings(tmp_path: Path):
    """A corpus with the light-crawl failure shape (single ``본문``
    section per page) reliably triggers Phase 5.1 warnings, so this is a
    stable fixture for the fail-on-warning gate."""
    pages = [
        _page(
            page_id=f"p{i}",
            sections=[
                _section(page_id=f"p{i}", order=0, heading_path=["본문"], depth=1)
            ],
        )
        for i in range(4)
    ]
    chunks = [
        _chunk(doc_id=f"p{i}", chunk_id=f"c{i}", section_path=["본문"])
        for i in range(4)
    ]
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
            "--fail-on-warning",
        ]
    )
    assert rc == 1
    # Even on failure, the JSON + Markdown reports must be written.
    assert (out_dir / "crawl_v4_audit_report.json").exists()
    assert (out_dir / "crawl_v4_audit_report.md").exists()
    obj = json.loads((out_dir / "crawl_v4_audit_report.json").read_text(encoding="utf-8"))
    assert obj["warnings"], "expected warnings in the JSON report"


def _long_chunk(
    *,
    doc_id: str,
    chunk_id: str,
    section_path: List[str],
    section_type: str,
) -> Dict[str, Any]:
    """A chunk whose text is well above the 60-char too_short threshold,
    so the chunk audit's existing length warnings don't fire."""
    text = (
        "이 작품의 본문은 충분히 긴 길이를 가지며 다양한 정보를 담고 있다. "
        "두 번째 문장에는 등장인물의 행동과 동기가 설명된다. "
        "세 번째 문장에서는 작품의 주제와 메시지를 살핀다. "
        "네 번째 문장은 평가와 반응을 다룬다."
    )
    return {
        "schema_version": "namu_anime_v4_rag_chunk",
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "title": doc_id,
        "section_id": f"sid_{doc_id}_{section_type}",
        "section_key": f"sk_{doc_id}_{section_type}",
        "section_path": section_path,
        "section_type": section_type,
        "chunk_text": text,
        "embedding_text": text,
        "metadata": {
            "source_url": None,
            "crawl_version": "v4",
            "has_spoiler": False,
            "text_length": len(text),
            "noise_score": 0.0,
            "is_stub": False,
            "is_table_like": False,
            "is_list_like": False,
        },
    }


def test_cli_fail_on_warning_returns_zero_when_clean(tmp_path: Path):
    """A multi-section, multi-work corpus with varied depths + section
    types should not trigger any audit warnings, so --fail-on-warning is
    a no-op. The fixture deliberately gives each page its own
    work_title and uses long chunk text so neither work-skew nor
    too-short warnings fire."""
    pages = []
    chunks = []
    # 6 distinct works × 3 sections × 1 chunk each → no skew, no duplicates,
    # 18 chunks total, work_skew_warn_ratio=0.30 means each work owns 1/6 < 30%.
    for i in range(6):
        pid = f"p{i}"
        wid = f"work_{i}"
        wtitle = f"작품_{i}"
        page = {
            "schema_version": "namu_anime_v4_page",
            "page_id": pid,
            "work_id": wid,
            "work_title": wtitle,
            "page_title": wtitle,
            "page_type": "work",
            "relation": "main",
            "canonical_url": f"https://namu.wiki/w/{pid}",
            "aliases": [f"alias_{i}_a", f"alias_{i}_b"],
            "source": {
                "site": "namu.wiki",
                "fetched_at": "2026-04-01T00:00:00",
                "revision_time": None,
            },
            "sections": [
                _section(
                    page_id=pid,
                    order=0,
                    heading_path=["줄거리", "1기"],
                    depth=2,
                    section_type="synopsis",
                ),
                _section(
                    page_id=pid,
                    order=1,
                    heading_path=["등장인물", "주인공"],
                    depth=2,
                    section_type="character",
                ),
                _section(
                    page_id=pid,
                    order=2,
                    heading_path=["설정"],
                    depth=1,
                    section_type="setting",
                ),
            ],
        }
        pages.append(page)
        for st, path in (
            ("synopsis", ["줄거리", "1기"]),
            ("character", ["등장인물", "주인공"]),
            ("setting", ["설정"]),
        ):
            chunks.append(
                _long_chunk(
                    doc_id=pid,
                    chunk_id=f"c_{pid}_{st}",
                    section_path=path,
                    section_type=st,
                )
            )
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
            "--fail-on-warning",
        ]
    )
    assert rc == 0
    obj = json.loads((out_dir / "crawl_v4_audit_report.json").read_text(encoding="utf-8"))
    assert obj["warnings"] == []


def test_cli_without_fail_on_warning_returns_zero_even_with_warnings(tmp_path: Path):
    """Without --fail-on-warning, audit_crawl_v4 must keep returning 0
    regardless of warnings (existing CI behaviour preserved)."""
    pages = [
        _page(
            page_id="p0",
            sections=[
                _section(page_id="p0", order=0, heading_path=["본문"], depth=1)
            ],
        )
    ]
    chunks = [_chunk(doc_id="p0", chunk_id="c0", section_path=["본문"])]
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
        ]
    )
    assert rc == 0
