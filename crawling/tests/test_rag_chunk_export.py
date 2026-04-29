"""Tests for the Phase 2 RAG chunk exporter.

The exporter is a pure projection: pages_v4 dicts -> RagChunkV4 records.
Tests stay synthetic (no real namu data) so they run in milliseconds.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from eval.harness.dataset_v4_schema import (
    SCHEMA_VERSION_PAGE,
    make_section_key,
    sha1_id,
)
from eval.harness.rag_chunk_export import (
    DEFAULT_MIN_CHARS,
    export_jsonl,
    export_rag_chunks,
)
from eval.harness.rag_chunk_schema import (
    EMBEDDING_TEXT_VARIANTS,
    SCHEMA_VERSION_RAG_CHUNK,
    RagChunkV4,
    build_rag_embedding_text,
    make_chunk_id,
)


# ---------------------------------------------------------------- fixtures


def _section(
    *,
    heading: List[str],
    section_type: str = "setting",
    clean_text: str,
    page_id: str = "page1",
    order: int = 0,
    quality: Optional[Dict[str, Any]] = None,
    section_key: Optional[str] = None,
    section_id: Optional[str] = None,
    links: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Build a minimal section dict matching the v4 page schema layout."""
    sk = section_key or make_section_key(page_id=page_id, heading_path=heading)
    sid = section_id or sha1_id(page_id, " > ".join(heading), order)
    q = {
        "text_length": len(clean_text),
        "noise_score": 0.0,
        "is_stub": False,
        "has_spoiler": False,
        "is_table_like": False,
        "is_list_like": False,
    }
    if quality:
        q.update(quality)
    return {
        "section_id": sid,
        "section_key": sk,
        "heading_path": heading,
        "depth": 1,
        "order": order,
        "text": clean_text,
        "links": links or [],
        "section_type": section_type,
        "raw_text": clean_text,
        "clean_text": clean_text,
        "summary": None,
        "keywords": [],
        "entities": [],
        "relations": [],
        "qa_candidates": [],
        "quality": q,
    }


def _page(
    *,
    page_id: str = "page1",
    title: str = "귀멸의 칼날",
    aliases: Optional[List[str]] = None,
    canonical_url: Optional[str] = "https://namu.wiki/w/test",
    sections: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION_PAGE,
        "page_id": page_id,
        "work_id": "w1",
        "work_title": title,
        "page_title": title,
        "page_type": "work",
        "relation": "main",
        "canonical_url": canonical_url,
        "parent_url": None,
        "aliases": aliases or [],
        "categories": [],
        "source": {"site": "namu.wiki", "fetched_at": None, "revision_time": None},
        "crawl": {
            "seed_title": title,
            "depth": 0,
            "discovery_reason": "root",
            "parent_page_id": None,
        },
        "sections": sections or [],
        "generated_summary": {"model": None, "text": None, "bullets": [], "created_at": None},
        "document_quality": {
            "total_text_length": 0,
            "section_count": len(sections or []),
            "valid_section_count": len(sections or []),
            "is_low_quality": False,
            "reason": None,
        },
    }


# ---------------------------------------------------------------- basic exporter


def test_export_yields_chunks_for_valid_section():
    body = (
        "호흡은 귀살대의 기본 전투 기술이다. 카마도 탄지로는 물의 호흡을 사용한다. "
        "물의 호흡에는 다양한 형이 존재한다. 추가 설명이 더 있다. " * 3
    )
    page = _page(
        sections=[_section(heading=["설정", "호흡"], section_type="setting", clean_text=body)],
    )
    chunks = list(export_rag_chunks([page], embedding_text_variant="title_section"))
    assert len(chunks) >= 1
    c = chunks[0]
    assert c.chunk_id
    assert c.doc_id == "page1"
    assert c.title == "귀멸의 칼날"
    assert c.section_id  # legacy still present
    assert c.section_key  # phase 1 stable key present
    assert c.section_path == ["설정", "호흡"]
    assert c.section_type == "setting"
    assert c.chunk_text and len(c.chunk_text) >= DEFAULT_MIN_CHARS
    assert c.embedding_text


def test_doc_id_equals_page_id():
    page = _page(
        page_id="custom_page",
        sections=[
            _section(heading=["본문"], section_type="summary", clean_text="x" * 200)
        ],
    )
    chunks = list(export_rag_chunks([page]))
    assert all(c.doc_id == "custom_page" for c in chunks)


def test_chunk_text_uses_clean_text_when_available():
    """If clean_text differs from text, the exporter must prefer clean_text."""
    sec = _section(heading=["본문"], section_type="summary", clean_text="A" * 200)
    sec["text"] = "B" * 200  # raw fallback we must NOT use
    sec["raw_text"] = "C" * 200
    page = _page(sections=[sec])
    chunks = list(export_rag_chunks([page]))
    assert chunks
    assert all(c.chunk_text.startswith("A") for c in chunks)


def test_chunk_text_falls_back_to_text_when_no_clean_text():
    sec = _section(heading=["본문"], section_type="summary", clean_text="")
    sec["clean_text"] = ""
    sec["text"] = "본문 텍스트가 충분히 길게 들어 있어서 청크 한 개가 만들어질 수 있다. " * 3
    sec["raw_text"] = ""
    sec["quality"]["text_length"] = len(sec["text"])
    page = _page(sections=[sec])
    chunks = list(export_rag_chunks([page]))
    assert chunks
    assert "본문 텍스트가 충분히" in chunks[0].chunk_text


def test_chunk_text_falls_back_to_raw_text_when_others_empty():
    sec = _section(heading=["본문"], section_type="summary", clean_text="")
    sec["clean_text"] = ""
    sec["text"] = ""
    sec["raw_text"] = "raw 본문이 직접 사용되는 경우가 있을 수 있다. 충분히 깁니다. " * 3
    sec["quality"]["text_length"] = len(sec["raw_text"])
    page = _page(sections=[sec])
    chunks = list(export_rag_chunks([page]))
    assert chunks
    assert "raw 본문" in chunks[0].chunk_text


# ---------------------------------------------------------------- chunk_id


def test_make_chunk_id_is_deterministic():
    a = make_chunk_id(page_id="p", section_key="sk", chunk_text="텍스트")
    b = make_chunk_id(page_id="p", section_key="sk", chunk_text="텍스트")
    assert a == b


def test_chunk_id_changes_when_chunk_text_changes():
    a = make_chunk_id(page_id="p", section_key="sk", chunk_text="첫 번째")
    b = make_chunk_id(page_id="p", section_key="sk", chunk_text="두 번째")
    assert a != b


def test_chunk_id_uses_section_key_not_section_id():
    """Two sections with the same section_key but different section_ids
    must produce the same chunk_id for the same chunk_text."""
    text = "동일한 청크 텍스트입니다. " * 10
    sec_a = _section(
        heading=["설정"],
        section_type="setting",
        clean_text=text,
        section_key="stable_key",
        section_id="legacy_id_A",
    )
    sec_b = _section(
        heading=["설정"],
        section_type="setting",
        clean_text=text,
        section_key="stable_key",
        section_id="legacy_id_B",
    )
    page_a = _page(sections=[sec_a])
    page_b = _page(sections=[sec_b])
    chunks_a = list(export_rag_chunks([page_a]))
    chunks_b = list(export_rag_chunks([page_b]))
    ids_a = [c.chunk_id for c in chunks_a]
    ids_b = [c.chunk_id for c in chunks_b]
    assert ids_a == ids_b
    assert chunks_a[0].section_id != chunks_b[0].section_id


def test_chunk_id_stable_under_section_reorder():
    """Reordering sections inside a page must not change chunk_ids
    (because section_key doesn't depend on order)."""
    body_a = "본문 A 의 청크. " * 20
    body_b = "본문 B 의 청크. " * 20
    sec_a = _section(heading=["설정"], section_type="setting", clean_text=body_a, order=0)
    sec_b = _section(heading=["등장인물"], section_type="character", clean_text=body_b, order=1)
    page_forward = _page(sections=[sec_a, sec_b])
    # Re-order: same content, swapped order. ALSO regenerate section_keys to
    # match what the converter would produce — i.e. order-independent.
    sec_a2 = _section(heading=["설정"], section_type="setting", clean_text=body_a, order=1)
    sec_b2 = _section(heading=["등장인물"], section_type="character", clean_text=body_b, order=0)
    page_reverse = _page(sections=[sec_b2, sec_a2])

    ids_forward = sorted(c.chunk_id for c in export_rag_chunks([page_forward]))
    ids_reverse = sorted(c.chunk_id for c in export_rag_chunks([page_reverse]))
    assert ids_forward == ids_reverse


def test_duplicate_chunk_text_within_section_uses_occurrence_disambiguator():
    """If the same chunk_text shows up twice in one section, the two chunks
    must get different chunk_ids deterministically via the occurrence index."""
    duplicated = "동일 단락입니다. " * 20
    body = duplicated + "\n\n" + duplicated  # forces the splitter to emit twice
    page = _page(
        sections=[
            _section(heading=["설정"], section_type="setting", clean_text=body)
        ],
    )
    chunks = list(export_rag_chunks([page]))
    assert len(chunks) == 2
    # Both chunks must have the same text but distinct ids, deterministically.
    assert chunks[0].chunk_text == chunks[1].chunk_text
    assert chunks[0].chunk_id != chunks[1].chunk_id
    # Re-run: same input -> same two ids in the same order.
    chunks_again = list(export_rag_chunks([page]))
    assert [c.chunk_id for c in chunks] == [c.chunk_id for c in chunks_again]


# ---------------------------------------------------------------- low quality


def test_stub_section_excluded_by_default():
    page = _page(
        sections=[
            _section(
                heading=["짧은 섹션"],
                section_type="other",
                clean_text="짧음",
                quality={"is_stub": True, "text_length": 2},
            )
        ],
    )
    chunks = list(export_rag_chunks([page]))
    assert chunks == []


def test_table_like_section_excluded_by_default():
    page = _page(
        sections=[
            _section(
                heading=["표"],
                section_type="other",
                clean_text="이름 | 능력 | 설명\n탄지로 | 물의 호흡 | 주인공",
                quality={"is_table_like": True, "text_length": 100},
            )
        ],
    )
    chunks = list(export_rag_chunks([page]))
    assert chunks == []


def test_list_like_section_is_included_by_default():
    """애니메이션 list 섹션 (방영 목록 / OST 트랙)도 기본 포함."""
    body = "\n".join(f"- 1화: 에피소드 {i} 설명이 충분히 길다." for i in range(8))
    page = _page(
        sections=[
            _section(
                heading=["방영 목록"],
                section_type="episode",
                clean_text=body,
                quality={"is_list_like": True, "text_length": len(body)},
            )
        ],
    )
    chunks = list(export_rag_chunks([page]))
    assert len(chunks) >= 1
    assert chunks[0].metadata.is_list_like is True


def test_include_low_quality_flag_keeps_stub():
    page = _page(
        sections=[
            _section(
                heading=["짧은 섹션"],
                section_type="other",
                clean_text="짧음",
                quality={"is_stub": True, "text_length": 2},
            )
        ],
    )
    chunks = list(
        export_rag_chunks(
            [page],
            embedding_text_variant="raw",
            include_low_quality=True,
        )
    )
    assert len(chunks) == 1
    assert chunks[0].metadata.is_stub is True


def test_metadata_has_spoiler_propagated_from_quality():
    body = "스포일러 본문이 길게 적혀 있다. " * 20
    page = _page(
        sections=[
            _section(
                heading=["줄거리"],
                section_type="synopsis",
                clean_text=body,
                quality={"has_spoiler": True, "text_length": len(body)},
            )
        ],
    )
    chunks = list(export_rag_chunks([page]))
    assert chunks
    assert all(c.metadata.has_spoiler is True for c in chunks)


def test_metadata_carries_quality_fields():
    body = "본문 텍스트입니다. " * 30
    page = _page(
        sections=[
            _section(
                heading=["설정"],
                section_type="setting",
                clean_text=body,
                quality={
                    "noise_score": 0.25,
                    "is_table_like": False,
                    "is_list_like": False,
                    "is_stub": False,
                    "has_spoiler": False,
                    "text_length": len(body),
                },
            )
        ],
    )
    chunk = next(iter(export_rag_chunks([page])))
    assert chunk.metadata.noise_score == 0.25
    assert chunk.metadata.is_stub is False
    assert chunk.metadata.is_table_like is False
    assert chunk.metadata.crawl_version == "v4"
    assert chunk.metadata.text_length == len(chunk.chunk_text)


# ---------------------------------------------------------------- embedding variants


def test_variant_raw_returns_chunk_text_only():
    out = build_rag_embedding_text(
        variant="raw",
        title="귀멸의 칼날",
        aliases=["Demon Slayer"],
        section_path=["설정"],
        section_type="setting",
        chunk_text="본문 텍스트.",
    )
    assert out == "본문 텍스트."


def test_variant_title_includes_title_only():
    out = build_rag_embedding_text(
        variant="title",
        title="귀멸의 칼날",
        aliases=["Demon Slayer"],
        section_path=["설정"],
        section_type="setting",
        chunk_text="본문 텍스트.",
    )
    assert "제목: 귀멸의 칼날" in out
    assert "섹션:" not in out
    assert "별칭:" not in out
    assert "본문 텍스트." in out


def test_variant_title_section_includes_path_and_type():
    out = build_rag_embedding_text(
        variant="title_section",
        title="귀멸의 칼날",
        aliases=[],
        section_path=["설정", "호흡"],
        section_type="setting",
        chunk_text="본문.",
    )
    assert "제목: 귀멸의 칼날" in out
    assert "섹션: 설정 > 호흡" in out
    assert "섹션타입: setting" in out
    assert "별칭:" not in out  # no aliases -> never present in this variant
    assert "본문." in out


def test_variant_title_section_alias_includes_aliases_when_present():
    out = build_rag_embedding_text(
        variant="title_section_alias",
        title="귀멸의 칼날",
        aliases=["Demon Slayer", "鬼滅の刃"],
        section_path=["설정"],
        section_type="setting",
        chunk_text="본문.",
    )
    assert "제목: 귀멸의 칼날" in out
    assert "별칭: Demon Slayer, 鬼滅の刃" in out
    assert "섹션: 설정" in out
    assert "섹션타입: setting" in out


def test_variant_title_section_alias_skips_alias_line_when_empty():
    """별칭 줄은 aliases가 비어 있을 때 생략되어야 한다."""
    out = build_rag_embedding_text(
        variant="title_section_alias",
        title="귀멸의 칼날",
        aliases=[],
        section_path=["설정"],
        section_type="setting",
        chunk_text="본문.",
    )
    assert "별칭:" not in out
    # 다른 헤더는 정상
    assert "제목: 귀멸의 칼날" in out
    assert "섹션: 설정" in out
    # 빈 별칭 줄이 본문 직전에 두 줄짜리 공백으로 새지 않아야 함
    lines = out.splitlines()
    assert "" not in [ln.strip() for ln in lines if ln.strip().startswith("별칭")]


def test_unknown_variant_raises():
    with pytest.raises(ValueError):
        build_rag_embedding_text(
            variant="unknown",
            title="X",
            aliases=[],
            section_path=[],
            section_type="other",
            chunk_text="t",
        )


def test_all_declared_variants_are_accepted_by_export():
    body = "본문 텍스트입니다. " * 30
    page = _page(
        aliases=["Demon Slayer"],
        sections=[
            _section(heading=["설정"], section_type="setting", clean_text=body)
        ],
    )
    for v in EMBEDDING_TEXT_VARIANTS:
        chunks = list(export_rag_chunks([page], embedding_text_variant=v))
        assert chunks, f"variant {v} produced no chunks"


# ---------------------------------------------------------------- aliases


def test_aliases_propagated_to_chunk_record():
    page = _page(
        aliases=["Demon Slayer", "鬼滅の刃"],
        sections=[
            _section(heading=["설정"], section_type="setting", clean_text="x" * 200)
        ],
    )
    chunk = next(iter(export_rag_chunks([page])))
    assert chunk.aliases == ["Demon Slayer", "鬼滅の刃"]


# ---------------------------------------------------------------- file io


def test_jsonl_round_trip(tmp_path: Path):
    body = "충분히 긴 본문 청크 후보 텍스트입니다. " * 5
    page = _page(
        sections=[_section(heading=["설정"], section_type="setting", clean_text=body)],
    )
    src = tmp_path / "pages_v4.jsonl"
    src.write_text(json.dumps(page, ensure_ascii=False) + "\n", encoding="utf-8")
    out = tmp_path / "rag_chunks.jsonl"
    n = export_jsonl(src, out, embedding_text_variant="title_section")
    assert n >= 1
    lines = out.read_text(encoding="utf-8").splitlines()
    assert len(lines) == n
    for line in lines:
        obj = json.loads(line)
        assert obj["schema_version"] == SCHEMA_VERSION_RAG_CHUNK
        assert obj["chunk_id"]
        assert obj["doc_id"] == page["page_id"]
        assert obj["section_id"]  # legacy
        assert obj["section_key"]  # stable
        assert obj["section_type"] == "setting"
        assert "metadata" in obj and isinstance(obj["metadata"], dict)
        assert obj["metadata"]["crawl_version"] == "v4"


def test_unknown_variant_in_export_raises():
    page = _page(
        sections=[_section(heading=["설정"], section_type="setting", clean_text="x" * 200)],
    )
    with pytest.raises(ValueError):
        list(export_rag_chunks([page], embedding_text_variant="weird"))


def test_pages_without_required_ids_are_skipped():
    bad = _page()
    bad["page_id"] = ""
    chunks = list(export_rag_chunks([bad]))
    assert chunks == []


def test_section_without_section_key_or_id_is_skipped():
    sec = _section(heading=["설정"], section_type="setting", clean_text="x" * 200)
    sec["section_key"] = ""
    sec["section_id"] = ""
    page = _page(sections=[sec])
    chunks = list(export_rag_chunks([page]))
    assert chunks == []


def test_chunk_id_uniqueness_under_normal_inputs():
    body_a = "첫 번째 섹션의 본문 청크 후보입니다. " * 20
    body_b = "두 번째 섹션의 본문 청크 후보입니다. " * 20
    page = _page(
        sections=[
            _section(heading=["설정"], section_type="setting", clean_text=body_a, order=0),
            _section(heading=["등장인물"], section_type="character", clean_text=body_b, order=1),
        ]
    )
    chunks = list(export_rag_chunks([page]))
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
