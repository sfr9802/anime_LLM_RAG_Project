"""Unit tests for the conservative text_cleaner module.

The cleaner must (a) remove obvious namu.wiki UI residue (footnotes, edit
markers, toggle leftovers, zero-width chars, control chars), (b) normalise
whitespace without destroying paragraph breaks, (c) dedupe consecutive
duplicate paragraphs, and (d) **preserve proper nouns** — character /
work names must never be touched.

The quality probe must produce stable heuristic flags on the cleaned text.
"""

from __future__ import annotations

from eval.harness.text_cleaner import (
    STUB_THRESHOLD,
    clean_text,
    section_quality,
)


def test_footnote_markers_are_removed():
    raw = "주인공[1]은 학생이다.[*] 그는 평범하다.[주1]"
    cleaned = clean_text(raw)
    assert "[1]" not in cleaned
    assert "[*]" not in cleaned
    assert "[주1]" not in cleaned
    # body words survive
    assert "주인공" in cleaned
    assert "학생" in cleaned


def test_edit_trace_markers_are_removed():
    raw = "본문 한 문장.[편집] 다음 문장.[수정]"
    cleaned = clean_text(raw)
    assert "[편집]" not in cleaned
    assert "[수정]" not in cleaned
    assert "본문 한 문장" in cleaned


def test_toggle_residue_is_removed():
    raw = "내용 시작\n펼치기 · 접기\n내용 본문"
    cleaned = clean_text(raw)
    assert "펼치기" not in cleaned
    assert "내용 본문" in cleaned


def test_zero_width_and_control_chars_are_removed():
    raw = "주인공​은‌ 학생‍이다."
    cleaned = clean_text(raw)
    assert "​" not in cleaned
    assert "‌" not in cleaned
    assert "" not in cleaned
    assert "주인공은 학생이다" in cleaned


def test_whitespace_collapsed_but_paragraphs_preserved():
    raw = "문단 1.\n\n\n\n문단    2.\n\n\n문단 3."
    cleaned = clean_text(raw)
    assert cleaned == "문단 1.\n\n문단 2.\n\n문단 3."


def test_duplicate_paragraphs_deduped():
    raw = "같은 문단입니다.\n\n같은 문단입니다.\n\n다른 문단입니다."
    cleaned = clean_text(raw)
    assert cleaned.count("같은 문단입니다") == 1
    assert "다른 문단입니다" in cleaned


def test_proper_nouns_are_preserved():
    raw = "카마도 탄지로는 귀살대 소속이며 물의 호흡을 사용한다.[1]"
    cleaned = clean_text(raw)
    assert "카마도 탄지로" in cleaned
    assert "귀살대" in cleaned
    assert "물의 호흡" in cleaned


def test_empty_input_returns_empty_string():
    assert clean_text("") == ""
    assert clean_text(None) == ""  # type: ignore[arg-type]


def test_quality_stub_flag():
    text = "짧은 본문"
    q = section_quality(text, text)
    assert q.is_stub is True
    assert q.text_length == len(text)
    assert q.noise_score == 0.0


def test_quality_long_text_is_not_stub():
    text = "충분히 긴 본문이다. " * 10  # > STUB_THRESHOLD
    q = section_quality(text, text)
    assert q.text_length >= STUB_THRESHOLD
    assert q.is_stub is False


def test_quality_table_like_flag():
    table = (
        "이름 | 소속 | 능력\n"
        "탄지로 | 귀살대 | 물의 호흡\n"
        "젠이츠 | 귀살대 | 번개의 호흡\n"
        "이노스케 | 귀살대 | 짐승의 호흡"
    )
    q = section_quality(table, table)
    assert q.is_table_like is True


def test_quality_list_like_flag():
    bullet_text = "\n".join(f"- 항목 {i}" for i in range(8))
    q = section_quality(bullet_text, bullet_text)
    assert q.is_list_like is True


def test_quality_spoiler_flag():
    raw = "[스포일러] 결말에서 주인공이 사망한다."
    cleaned = clean_text(raw)
    q = section_quality(raw, cleaned)
    assert q.has_spoiler is True


def test_quality_noise_score_when_a_lot_is_stripped():
    raw = "원본 텍스트 짧음 " + "[편집]" * 100
    cleaned = clean_text(raw)
    q = section_quality(raw, cleaned)
    assert 0.0 < q.noise_score <= 1.0
    # cleaning kept the meaningful prefix
    assert "원본 텍스트" in cleaned


def test_quality_noise_score_zero_when_nothing_to_clean():
    raw = "이미 깨끗한 본문이다. 충분히 길다." * 3
    cleaned = clean_text(raw)
    q = section_quality(raw, cleaned)
    assert q.noise_score == 0.0


def test_clean_text_idempotent():
    raw = "[편집] 어떤 본문[1]\n\n\n다른 단락 [*] 끝."
    once = clean_text(raw)
    twice = clean_text(once)
    assert once == twice
