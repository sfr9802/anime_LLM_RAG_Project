"""Unit tests for the rule-based section_type classifier.

The classifier is intentionally simple — it must (a) recognise common
namu.wiki / anime-doc heading vocabulary, (b) prefer specific patterns over
generic ones, and (c) defer to ``page_relation`` when the heading itself is
generic ("본문" etc.).
"""

from __future__ import annotations

import pytest

from eval.harness.section_classifier import (
    SECTION_TYPE_PATTERNS,
    classify_section_type,
)


@pytest.mark.parametrize(
    "heading, expected",
    [
        # character
        (["등장인물"], "character"),
        (["등장 인물"], "character"),
        (["캐릭터"], "character"),
        (["Character"], "character"),
        (["인물 소개"], "character"),
        # synopsis vs summary
        (["줄거리"], "synopsis"),
        (["스토리"], "synopsis"),
        (["plot"], "synopsis"),
        (["줄거리 요약"], "summary"),
        (["개요"], "summary"),
        (["소개"], "summary"),
        (["overview"], "summary"),
        # worldview / setting / concept
        (["세계관"], "worldview"),
        (["설정"], "setting"),
        (["설정/세계관"], "worldview"),  # 'worldview' wins (more specific)
        (["용어"], "setting"),
        (["능력"], "setting"),
        (["스킬"], "setting"),
        (["컨셉"], "concept"),
        # episode
        (["에피소드"], "episode"),
        (["방영 목록"], "episode"),
        (["방영목록"], "episode"),
        (["회차"], "episode"),
        # evaluation
        (["평가"], "evaluation"),
        (["흥행"], "evaluation"),
        (["반응"], "evaluation"),
        (["리뷰"], "evaluation"),
        # production
        (["스태프"], "production"),
        (["감독"], "production"),
        (["원작"], "production"),
        # music
        (["음악"], "music"),
        (["OST"], "music"),
        (["오프닝"], "music"),
        # trivia
        (["기타"], "trivia"),
        (["여담"], "trivia"),
    ],
)
def test_classifier_recognises_common_headings(heading, expected):
    assert classify_section_type(heading) == expected


def test_generic_heading_falls_back_to_page_relation():
    # "본문" alone has no signal -> rely on relation hint
    assert classify_section_type(["본문"], page_relation="main") == "summary"
    assert classify_section_type(["본문"], page_relation="character") == "character"
    assert classify_section_type(["본문"], page_relation="setting") == "setting"
    assert classify_section_type(["본문"], page_relation="plot") == "synopsis"
    assert classify_section_type(["본문"], page_relation="review") == "evaluation"
    assert classify_section_type(["본문"], page_relation="production") == "production"
    assert classify_section_type(["본문"], page_relation="episode") == "episode"


def test_unknown_heading_falls_back_to_other():
    assert classify_section_type(["완전 모르는 섹션 제목"]) == "other"
    assert classify_section_type([]) == "other"
    assert classify_section_type([""]) == "other"
    # No relation hint either -> still other
    assert classify_section_type(["본문"], page_relation=None) == "other"


def test_specific_pattern_beats_generic():
    # 줄거리 요약 must yield summary, NOT synopsis (since both keywords overlap)
    assert classify_section_type(["줄거리 요약"]) == "summary"
    # 음악 is not classified as production despite naming nearby OST/staff
    assert classify_section_type(["주제가"]) == "music"


def test_classifier_table_is_non_empty_and_typed():
    # sanity: rule table itself is non-trivial — guards against accidental wipes
    assert len(SECTION_TYPE_PATTERNS) >= 8
    # every pattern entry maps to a string section type
    for pattern, kind in SECTION_TYPE_PATTERNS:
        assert isinstance(pattern, str) and pattern
        assert isinstance(kind, str) and kind


def test_normalization_handles_whitespace_and_case():
    assert classify_section_type(["  등장인물  "]) == "character"
    assert classify_section_type(["OPENING"]) == "music"
    assert classify_section_type(["Episodes"]) == "episode"
