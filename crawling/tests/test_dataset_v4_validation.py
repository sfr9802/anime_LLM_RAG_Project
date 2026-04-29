"""Unit tests for the v4 validation module.

The tests construct minimal page/chunk dicts directly to keep validation
decoupled from the converter's exact behavior.
"""

from __future__ import annotations

from eval.harness.dataset_v4_schema import (
    SCHEMA_VERSION_CHUNK,
    SCHEMA_VERSION_PAGE,
)
from eval.harness.dataset_v4_validation import (
    SHORT_CHUNK_THRESHOLD,
    render_markdown,
    validate,
)


def _page(
    *,
    page_id: str,
    work_title: str = "Work",
    page_title: str = "Page",
    page_type: str = "work",
    relation: str = "main",
    canonical_url: str | None = "https://namu.wiki/w/Work",
    discovery_reason: str = "root",
    sections=None,
) -> dict:
    return {
        "schema_version": SCHEMA_VERSION_PAGE,
        "page_id": page_id,
        "work_id": "w1",
        "work_title": work_title,
        "page_title": page_title,
        "page_type": page_type,
        "relation": relation,
        "canonical_url": canonical_url,
        "parent_url": None,
        "aliases": [],
        "categories": [],
        "source": {"site": "namu.wiki", "fetched_at": None, "revision_time": None},
        "crawl": {
            "seed_title": "Work",
            "depth": 0,
            "discovery_reason": discovery_reason,
            "parent_page_id": None,
        },
        "sections": sections or [],
        "generated_summary": {"model": None, "text": None, "bullets": [], "created_at": None},
    }


def _chunk(
    *,
    chunk_id: str,
    page_id: str = "p1",
    text: str = "텍스트",
    section_path=None,
    is_short: bool | None = None,
    is_empty: bool = False,
    schema_version: str = SCHEMA_VERSION_CHUNK,
) -> dict:
    if section_path is None:
        section_path = ["본문"]
    char_len = len(text)
    if is_short is None:
        is_short = char_len < SHORT_CHUNK_THRESHOLD
    return {
        "schema_version": schema_version,
        "chunk_id": chunk_id,
        "page_id": page_id,
        "work_id": "w1",
        "work_title": "Work",
        "page_title": "Page",
        "page_type": "work",
        "relation": "main",
        "section_path": section_path,
        "chunk_index": 0,
        "text": text,
        "text_for_embedding": text,
        "char_len": char_len,
        "token_estimate": max(1, char_len // 2),
        "retrieval_tags": [],
        "source_url": None,
        "quality": {
            "is_empty": is_empty or char_len == 0,
            "is_short": is_short,
            "is_truncated": False,
            "boilerplate_removed": True,
        },
    }


def test_basic_counts_and_distributions():
    pages = [
        _page(page_id="a", page_type="work", relation="main"),
        _page(page_id="b", page_type="character", relation="character", discovery_reason="subpage"),
        _page(page_id="c", page_type="setting", relation="setting", discovery_reason="subpage"),
    ]
    chunks = [
        _chunk(chunk_id="c1", text="긴 텍스트가 충분히 길어야 하므로 적당한 길이의 텍스트를 작성합니다 짧지 않게."),
        _chunk(chunk_id="c2", text="짧음"),
    ]
    report = validate(pages, chunks, input_count=3)
    rd = report.to_dict()
    assert rd["input_count"] == 3
    assert rd["pages_count"] == 3
    assert rd["chunks_count"] == 2
    assert rd["page_type_counts"]["work"] == 1
    assert rd["page_type_counts"]["character"] == 1
    assert rd["page_type_counts"]["setting"] == 1
    assert rd["promoted_subpage_count"] == 2


def test_duplicate_page_id_detection():
    pages = [
        _page(page_id="dup"),
        _page(page_id="dup"),
        _page(page_id="other"),
    ]
    report = validate(pages, [])
    assert report.to_dict()["duplicate_page_id_count"] == 1


def test_duplicate_chunk_id_detection():
    chunks = [
        _chunk(chunk_id="x"),
        _chunk(chunk_id="x"),
        _chunk(chunk_id="x"),
        _chunk(chunk_id="y"),
    ]
    report = validate([], chunks)
    # 3 occurrences of x => 2 duplicates
    assert report.to_dict()["duplicate_chunk_id_count"] == 2


def test_short_chunk_detection():
    chunks = [
        _chunk(chunk_id="a", text="짧음"),
        _chunk(chunk_id="b", text="x" * (SHORT_CHUNK_THRESHOLD + 5)),
    ]
    report = validate([], chunks)
    rd = report.to_dict()
    assert rd["short_chunk_count"] == 1
    assert rd["chunk_char_len"]["max"] == SHORT_CHUNK_THRESHOLD + 5


def test_missing_field_counts():
    pages = [
        _page(page_id="a", work_title="", page_title="", canonical_url=None),
        _page(page_id="b", work_title="x", page_title="x", canonical_url=None),
        _page(page_id="c", work_title="x", page_title="x", canonical_url="https://x"),
    ]
    report = validate(pages, [])
    rd = report.to_dict()
    assert rd["missing_work_title_count"] == 1
    assert rd["missing_page_title_count"] == 1
    assert rd["missing_source_url_count"] == 2


def test_generic_title_count():
    pages = [
        _page(page_id="a", page_title="등장인물"),
        _page(page_id="b", page_title="설정"),
        _page(page_id="c", page_title="진짜 작품 제목"),
    ]
    report = validate(pages, [])
    rd = report.to_dict()
    assert rd["generic_page_title_count"] == 2
    titles = dict(rd["top_generic_titles"])
    assert titles.get("등장인물") == 1
    assert titles.get("설정") == 1


def test_empty_section_count():
    pages = [
        _page(
            page_id="a",
            sections=[
                {"section_id": "s1", "heading_path": ["본문"], "depth": 1, "order": 0, "text": "내용", "links": []},
                {"section_id": "s2", "heading_path": ["빈"], "depth": 1, "order": 1, "text": "", "links": []},
                {"section_id": "s3", "heading_path": ["공백"], "depth": 1, "order": 2, "text": "   ", "links": []},
            ],
        ),
    ]
    report = validate(pages, [])
    assert report.to_dict()["empty_section_count"] == 2


def test_schema_version_mismatch_detected():
    pages = [
        _page(page_id="a"),
        {**_page(page_id="b"), "schema_version": "wrong"},
    ]
    chunks = [
        _chunk(chunk_id="a"),
        _chunk(chunk_id="b", schema_version="wrong"),
    ]
    report = validate(pages, chunks).to_dict()
    assert report["schema_version_mismatch_pages"] == 1
    assert report["schema_version_mismatch_chunks"] == 1


def test_render_markdown_smoke():
    pages = [_page(page_id="a")]
    chunks = [_chunk(chunk_id="x")]
    report = validate(pages, chunks, input_count=1, extra_warnings=["something noisy"])
    md = render_markdown(report)
    assert "validation report" in md
    assert "Page type distribution" in md
    assert "Chunk length stats" in md
    assert "something noisy" in md
