"""Phase 1 integration tests.

Covers the new fields plumbed through ``namu_v3_to_v4.convert_record``:

* ``section_key`` is order-stable when section paths are unique.
* duplicate section paths get a deterministic disambiguator.
* ``section_id`` (legacy) keeps its order-dependent v3->v4 formula intact.
* ``raw_text`` is preserved exactly.
* ``clean_text`` is populated and matches the legacy ``text`` field.
* ``section_type`` is filled by the rule-based classifier.
* ``quality`` (per section) and ``document_quality`` (per page) are computed.
* the schema additions do not break existing v3->v4 regressions.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from eval.harness.dataset_v4_schema import (
    DocumentQuality,
    SectionQuality,
    make_section_key,
    normalize_section_path,
)
from eval.harness.namu_v3_to_v4 import convert_record


def _record(*, section_order: List[str], sections: Dict[str, dict]) -> dict:
    return {
        "seed": "테스트 작품",
        "title": "테스트 작품",
        "sections": sections,
        "section_order": section_order,
        "meta": {"seed_title": "테스트 작품", "depth": 0, "fetched_at": "2026-04-30T00:00:00"},
    }


def _section(text: str, *, urls: Optional[List[str]] = None) -> dict:
    return {
        "text": text,
        "chunks": [text],
        "urls": urls or ["https://namu.wiki/w/test"],
    }


# ---------------------------------------------------------------- section_key


def test_section_key_is_order_stable_for_unique_paths():
    """Reordering sections must not change section_key when paths are unique.
    section_id (legacy) is allowed to change because it intentionally mixes
    in ``order`` for backward-compat with the v3->v4 formula.
    """
    a = _record(
        section_order=["본문", "등장인물", "설정"],
        sections={
            "본문": _section("본문 내용입니다."),
            "등장인물": _section("등장인물 설명."),
            "설정": _section("설정 설명."),
        },
    )
    b = _record(
        section_order=["설정", "본문", "등장인물"],
        sections=a["sections"],
    )

    pages_a, _, _ = convert_record(a)
    pages_b, _, _ = convert_record(b)

    keys_a = {s.heading_path[0]: s.section_key for s in pages_a[0].sections}
    keys_b = {s.heading_path[0]: s.section_key for s in pages_b[0].sections}

    assert keys_a == keys_b
    # section_id IS allowed to differ — ordering changed
    ids_a = {s.heading_path[0]: s.section_id for s in pages_a[0].sections}
    ids_b = {s.heading_path[0]: s.section_id for s in pages_b[0].sections}
    assert ids_a != ids_b


def test_section_key_helper_is_deterministic():
    k1 = make_section_key(page_id="p", heading_path=["설정", "세계관"])
    k2 = make_section_key(page_id="p", heading_path=["설정", "세계관"])
    assert k1 == k2
    # ID hashing normalises whitespace + case via normalize_text_for_id
    k3 = make_section_key(page_id="p", heading_path=["  설정 ", "세계관"])
    assert k1 == k3


def test_section_key_differs_across_pages_and_paths():
    k_root_a = make_section_key(page_id="page1", heading_path=["설정"])
    k_other_a = make_section_key(page_id="page2", heading_path=["설정"])
    k_root_b = make_section_key(page_id="page1", heading_path=["등장인물"])
    assert k_root_a != k_other_a
    assert k_root_a != k_root_b


def test_duplicate_path_uses_deterministic_disambiguator():
    """When the same heading is used twice in a single page, the second
    occurrence must get a different section_key, deterministically."""
    record = _record(
        section_order=["본문", "본문"],
        sections={
            # In real namu pages duplicates are rare; we simulate by reusing
            # the same heading. The converter still gets only one entry from
            # the dict, but section_order tells it to walk the same heading
            # twice so we hit the duplicate-path branch.
            "본문": _section("어떤 내용이 충분히 들어 있다. 이 텍스트는 stub 임계값을 넘긴다."),
        },
    )
    # The converter dedupes via dict.get, so reusing the same key in
    # section_order still only walks one section. Build the duplicate
    # condition by hand: re-call _make_section through convert_record
    # using two distinct section dicts that NORMALIZE to the same path.
    record2 = _record(
        section_order=["본문", " 본문 "],
        sections={
            "본문": _section("첫 번째 본문 텍스트입니다. 충분히 깁니다. 한 번 더 깁니다."),
            " 본문 ": _section("두 번째 본문 텍스트입니다. 약간 다릅니다. 충분히 깁니다."),
        },
    )

    pages, _, _ = convert_record(record2)
    sections = pages[0].sections
    assert len(sections) == 2
    # section_keys must differ thanks to the occurrence disambiguator
    assert sections[0].section_key != sections[1].section_key
    # ...and both must have the same normalised path (the disambiguator is
    # the only thing distinguishing them)
    norm0 = normalize_section_path(sections[0].heading_path)
    norm1 = normalize_section_path(sections[1].heading_path)
    assert norm0 == norm1


def test_section_key_present_on_every_section():
    record = _record(
        section_order=["본문", "등장인물", "설정"],
        sections={
            "본문": _section("본문."),
            "등장인물": _section("인물."),
            "설정": _section("설정."),
        },
    )
    pages, _, _ = convert_record(record)
    for s in pages[0].sections:
        assert s.section_key, f"section {s.heading_path} missing section_key"
        assert isinstance(s.section_key, str)
        # legacy section_id also still present
        assert s.section_id and isinstance(s.section_id, str)


# ---------------------------------------------------------------- raw_text / clean_text


def test_raw_text_preserved_verbatim_when_clean_skips_nothing():
    raw = "이미 깨끗한 본문이다. 충분히 깁니다. 다른 문장도 있습니다."
    record = _record(
        section_order=["본문"],
        sections={"본문": _section(raw)},
    )
    pages, _, _ = convert_record(record)
    sec = pages[0].sections[0]
    assert sec.raw_text == raw
    # clean_text == text (back-compat) and equal to raw_text in this case
    assert sec.clean_text == sec.text
    assert sec.clean_text == raw


def test_clean_text_strips_footnotes_but_raw_text_keeps_them():
    raw = "주인공[1]은 학생이다.[편집] 친구도 있다.[*]"
    record = _record(
        section_order=["본문"],
        sections={"본문": _section(raw)},
    )
    pages, _, _ = convert_record(record)
    sec = pages[0].sections[0]
    assert sec.raw_text == raw  # untouched
    assert "[1]" in sec.raw_text
    assert "[1]" not in sec.clean_text
    assert "[편집]" not in sec.clean_text
    # body still present in clean_text
    assert "주인공" in sec.clean_text
    assert "학생" in sec.clean_text


def test_section_type_classified_per_heading():
    record = _record(
        section_order=["본문", "등장인물", "설정", "평가"],
        sections={
            "본문": _section("개요 텍스트."),
            "등장인물": _section("인물 텍스트."),
            "설정": _section("설정 텍스트."),
            "평가": _section("평가 텍스트."),
        },
    )
    pages, _, _ = convert_record(record)
    by_heading = {s.heading_path[0]: s.section_type for s in pages[0].sections}
    # 본문 falls back to root relation hint = "main" -> "summary"
    assert by_heading["본문"] == "summary"
    assert by_heading["등장인물"] == "character"
    assert by_heading["설정"] == "setting"
    assert by_heading["평가"] == "evaluation"


# ---------------------------------------------------------------- quality probes


def test_section_quality_populated():
    record = _record(
        section_order=["본문"],
        sections={"본문": _section("본문 텍스트입니다. 충분히 길게 작성되어 stub 임계값을 명확히 넘어가야 합니다." * 2)},
    )
    pages, _, _ = convert_record(record)
    sec = pages[0].sections[0]
    assert isinstance(sec.quality, SectionQuality)
    assert sec.quality.text_length > 0
    assert sec.quality.is_stub is False


def test_document_quality_rolled_up():
    record = _record(
        section_order=["본문", "등장인물"],
        sections={
            "본문": _section("길고 의미있는 본문 텍스트입니다. " * 5),
            "등장인물": _section("길고 의미있는 인물 설명 텍스트입니다. " * 5),
        },
    )
    pages, _, _ = convert_record(record)
    page = pages[0]
    assert isinstance(page.document_quality, DocumentQuality)
    assert page.document_quality.section_count == 2
    assert page.document_quality.valid_section_count >= 1
    assert page.document_quality.total_text_length > 0
    assert page.document_quality.is_low_quality is False


def test_document_quality_flags_low_quality_when_all_stub():
    record = _record(
        section_order=["본문"],
        sections={"본문": _section("짧음")},
    )
    pages, _, _ = convert_record(record)
    page = pages[0]
    assert page.document_quality.is_low_quality is True
    assert page.document_quality.reason == "all sections are stub/table/list"


# ---------------------------------------------------------------- placeholders


def test_phase1_placeholder_lists_default_empty():
    record = _record(
        section_order=["본문"],
        sections={"본문": _section("어떤 본문 내용입니다.")},
    )
    pages, _, _ = convert_record(record)
    sec = pages[0].sections[0]
    # keywords/entities/relations/qa_candidates are placeholders this phase
    assert sec.keywords == []
    assert sec.entities == []
    assert sec.relations == []
    assert sec.qa_candidates == []
    # but the schema fields are present and typed (i.e. iterable)
    assert isinstance(sec.keywords, list)
    assert isinstance(sec.entities, list)
    assert isinstance(sec.relations, list)
    assert isinstance(sec.qa_candidates, list)
