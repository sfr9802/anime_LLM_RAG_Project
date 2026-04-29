"""Unit tests for the v3 -> v4 converter.

Fixtures are tiny so the suite runs in milliseconds.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.harness.dataset_v4_schema import (
    SCHEMA_VERSION_CHUNK,
    SCHEMA_VERSION_PAGE,
    is_generic_title,
    relation_from_subpage_key,
    title_from_url,
)
from eval.harness.namu_v3_to_v4 import (
    convert_jsonl,
    convert_record,
    write_jsonl,
)


def _make_v3_record(
    *,
    seed: str = "테스트 작품",
    title: str | None = None,
    sections: dict | None = None,
    subpages: dict | None = None,
    summary: str = "테스트 작품의 요약",
    fetched_at: str = "2025-08-08T11:25:21.387434",
) -> dict:
    if title is None:
        title = seed
    if sections is None:
        sections = {
            "요약": {
                "text": summary,
                "bullets": ["핵심 1", "핵심 2"],
                "chunks": [summary, "- 핵심 1", "- 핵심 2"],
                "urls": [],
                "model": "gemma-2-9b-it",
                "ts": "2025-08-22T07:48:41+00:00",
            },
            "본문": {
                "text": (
                    "테스트 작품은 가공의 작품이다. 주인공은 평범한 학생이며, "
                    "어느 날 신비한 사건에 휘말리며 모험이 시작된다. "
                    "독자는 주인공의 성장을 따라간다."
                ),
                "chunks": [
                    "테스트 작품은 가공의 작품이다. 주인공은 평범한 학생이다.",
                    "어느 날 신비한 사건에 휘말리며 모험이 시작된다.",
                    "독자는 주인공의 성장을 따라간다.",
                ],
                "urls": ["https://namu.wiki/w/%ED%85%8C%EC%8A%A4%ED%8A%B8%20%EC%9E%91%ED%92%88"],
            },
        }
    return {
        "seed": seed,
        "title": title,
        "sections": sections,
        "section_order": list(sections.keys()),
        "meta": {"seed_title": seed, "depth": 0, "fetched_at": fetched_at},
        "doc_id": "abc123",
        "created_at": "2025-08-22T07:48:41+00:00",
        "summary": summary,
        "sum_bullets": ["핵심 1", "핵심 2"],
        "summary_bullets": ["핵심 1", "핵심 2"],
        "subpages": subpages or {},
    }


def test_root_document_becomes_work_page():
    record = _make_v3_record()
    pages, chunks, warnings = convert_record(record)

    assert len(pages) == 1
    root = pages[0]
    assert root.schema_version == SCHEMA_VERSION_PAGE
    assert root.work_title == "테스트 작품"
    assert root.page_title == "테스트 작품"
    assert root.page_type == "work"
    assert root.relation == "main"
    assert root.crawl.discovery_reason == "root"
    assert root.canonical_url is not None
    assert root.parent_url is None


def test_root_section_becomes_chunks_with_metadata():
    record = _make_v3_record()
    pages, chunks, _ = convert_record(record)
    root = pages[0]

    # 본문 section -> 3 chunks (요약 should NOT generate chunks)
    body_chunks = [c for c in chunks if c.section_path == ["본문"]]
    assert len(body_chunks) == 3

    # 요약 should be excluded from chunks (lives in generated_summary instead)
    summary_chunks = [c for c in chunks if c.section_path == ["요약"]]
    assert summary_chunks == []

    assert root.generated_summary.text and "테스트 작품" in root.generated_summary.text
    assert root.generated_summary.bullets

    chunk = body_chunks[0]
    assert chunk.schema_version == SCHEMA_VERSION_CHUNK
    assert chunk.work_title == "테스트 작품"
    assert chunk.page_title == "테스트 작품"
    assert chunk.page_type == "work"
    assert chunk.relation == "main"
    assert chunk.char_len == len(chunk.text)
    assert chunk.token_estimate >= 1


def test_text_for_embedding_includes_metadata():
    record = _make_v3_record()
    _, chunks, _ = convert_record(record)
    body = next(c for c in chunks if c.section_path == ["본문"])
    tfe = body.text_for_embedding
    assert "작품: 테스트 작품" in tfe
    assert "문서: 테스트 작품" in tfe
    assert "유형: work" in tfe
    assert "관계: main" in tfe
    assert "섹션: 본문" in tfe
    assert "본문: " in tfe
    assert body.text in tfe


def test_subpages_promoted_to_separate_pages():
    record = _make_v3_record(
        subpages={
            "등장인물": [
                {
                    "title": "테스트 작품/등장인물",
                    "summary": "주연들의 요약",
                    "raw_text": (
                        "주인공은 학생이며 평범하다. 그는 매일 학교를 다닌다.\n\n"
                        "조연 친구는 활발하고 명랑하다. 모험에 함께한다.\n\n"
                        "라이벌은 진중한 성격이다. 항상 견제한다."
                    ),
                    "url": "https://namu.wiki/w/%ED%85%8C%EC%8A%A4%ED%8A%B8%20%EC%9E%91%ED%92%88/%EB%93%B1%EC%9E%A5%EC%9D%B8%EB%AC%BC",
                    "parent": "등장인물",
                    "is_character": True,
                }
            ]
        }
    )
    pages, chunks, _ = convert_record(record)

    char_pages = [p for p in pages if p.page_type == "character"]
    assert len(char_pages) == 1
    cp = char_pages[0]
    assert cp.relation == "character"
    assert cp.page_type == "character"
    assert cp.crawl.discovery_reason == "subpage"
    assert cp.crawl.depth == 1
    assert cp.parent_url is not None
    assert cp.work_title == "테스트 작품"
    # page_title should be derived from URL (which carries the canonical "테스트 작품/등장인물")
    assert cp.page_title == "테스트 작품/등장인물"

    char_chunks = [c for c in chunks if c.page_id == cp.page_id]
    assert len(char_chunks) >= 3, "raw_text was split into paragraph chunks"
    for ch in char_chunks:
        assert ch.page_type == "character"
        assert ch.relation == "character"
        assert "유형: character" in ch.text_for_embedding


def test_generic_title_does_not_pollute_root_page_title():
    # v3 bug: title="등장인물" while seed is the actual work
    record = _make_v3_record(seed="건담 W", title="등장인물")
    pages, _, warnings = convert_record(record, line_number=42)
    root = pages[0]
    assert root.page_title == "건담 W"
    assert root.work_title == "건담 W"
    assert any("generic" in w for w in warnings)


def test_id_stability_for_same_input():
    record = _make_v3_record()
    p1, c1, _ = convert_record(record)
    p2, c2, _ = convert_record(record)
    assert [p.page_id for p in p1] == [p.page_id for p in p2]
    assert [c.chunk_id for c in c1] == [c.chunk_id for c in c2]


def test_subpage_relation_inference():
    assert relation_from_subpage_key("등장인물") == "character"
    assert relation_from_subpage_key("설정/세계관") == "setting"
    assert relation_from_subpage_key("줄거리") == "plot"
    assert relation_from_subpage_key("기타") == "other"
    assert relation_from_subpage_key(None) == "other"
    assert relation_from_subpage_key("Character") == "character"


def test_title_from_url_round_trip():
    url = "https://namu.wiki/w/%ED%85%8C%EC%8A%A4%ED%8A%B8%20%EC%9E%91%ED%92%88/%EB%93%B1%EC%9E%A5%EC%9D%B8%EB%AC%BC"
    assert title_from_url(url) == "테스트 작품/등장인물"
    assert title_from_url(None) is None


def test_is_generic_title_handles_whitespace_and_case():
    assert is_generic_title("등장인물")
    assert is_generic_title("  등장인물  ")
    assert is_generic_title("character") is False  # English not listed as generic by itself
    assert not is_generic_title("내 멋대로 작품")
    assert is_generic_title("") is True


def test_empty_section_is_dropped(tmp_path: Path):
    record = _make_v3_record(
        sections={
            "요약": {
                "text": "요약입니다.",
                "bullets": ["b"],
                "chunks": ["요약입니다."],
                "urls": [],
                "model": "x",
                "ts": "2025-01-01",
            },
            "본문": {
                "text": "본문 텍스트.",
                "chunks": ["본문 텍스트."],
                "urls": [],
            },
            "설정": {
                # empty: no text, no chunks
                "text": "",
                "chunks": [],
                "urls": [],
            },
        }
    )
    pages, chunks, warnings = convert_record(record)
    root = pages[0]
    headings = [s.heading_path for s in root.sections]
    assert ["설정"] not in headings
    assert any("section '설정' is empty" in w for w in warnings)


def test_jsonl_round_trip_via_files(tmp_path: Path):
    record = _make_v3_record(
        subpages={
            "등장인물": [
                {
                    "title": "테스트 작품/등장인물",
                    "raw_text": "내용 한 단락이다. 그리고 또 다른 단락.",
                    "url": "https://namu.wiki/w/test/char",
                    "parent": "등장인물",
                    "is_character": True,
                }
            ]
        }
    )
    src = tmp_path / "v3.jsonl"
    src.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    pages, chunks, warnings, input_count = convert_jsonl(src)
    assert input_count == 1
    pages_path = tmp_path / "pages_v4.jsonl"
    chunks_path = tmp_path / "chunks_v4.jsonl"
    n_pages = write_jsonl(pages, pages_path)
    n_chunks = write_jsonl(chunks, chunks_path)
    assert n_pages == len(pages)
    assert n_chunks == len(chunks)
    # round-trip: every line must be valid JSON with schema_version
    for line in pages_path.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        assert obj["schema_version"] == SCHEMA_VERSION_PAGE
    for line in chunks_path.read_text(encoding="utf-8").splitlines():
        obj = json.loads(line)
        assert obj["schema_version"] == SCHEMA_VERSION_CHUNK


def test_invalid_jsonl_lines_are_skipped(tmp_path: Path):
    record = _make_v3_record()
    src = tmp_path / "v3.jsonl"
    with src.open("w", encoding="utf-8") as f:
        f.write("not json\n")
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
        f.write("\n")  # blank
    pages, chunks, warnings, input_count = convert_jsonl(src)
    assert input_count == 1
    assert len(pages) == 1
