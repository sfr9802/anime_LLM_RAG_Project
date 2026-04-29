"""Rule-based section_type classifier.

Maps a section's ``heading_path`` (and an optional page-level ``relation``
hint) to one of the canonical ``SectionType`` values defined in
``dataset_v4_schema``.

This module is intentionally pure / dependency-free so it can be unit-tested
without the full converter pipeline. The rule table is exposed as
``SECTION_TYPE_PATTERNS`` so a future ML/LLM classifier can be swapped in
behind the same ``classify_section_type`` interface without touching the
converter.
"""

from __future__ import annotations

import re
from typing import Iterable, List, Optional, Sequence, Tuple

from .dataset_v4_schema import SectionType, normalize_text_for_id


# Each entry is (regex pattern, section_type). The patterns are checked in
# order; first match wins, so put more specific patterns before generic ones.
# All patterns run against the NFKC + lowercased + whitespace-collapsed form
# of ``" > ".join(heading_path)``, so multi-word headings like ``"설정 / 세계관"``
# normalize before matching.
SECTION_TYPE_PATTERNS: Tuple[Tuple[str, SectionType], ...] = (
    # --- character (checked before summary so that "인물 소개" wins over "소개") ---
    (r"\b(?:등장인물|등장\s*인물|캐릭터|character|cast|인물\s*소개)\b", "character"),

    # --- summary / synopsis ---
    # 줄거리 요약 must come before generic 줄거리 (which is plot/synopsis)
    (r"\b(?:줄거리\s*요약|개요\s*요약)\b", "summary"),
    (r"\b(?:개요|소개|introduction|overview|요약(?!\s*표))\b", "summary"),
    (r"\b(?:줄거리|스토리|story|plot|synopsis)\b", "synopsis"),

    # --- music (must come before production/setting since OST/주제가 are
    # sometimes nested under those) ---
    (
        r"\b(?:음악|ost|주제가|오프닝|엔딩|opening|ending|삽입곡|"
        r"사운드트랙|soundtrack|bgm)\b",
        "music",
    ),

    # --- evaluation ---
    (r"\b(?:평가|비판|반응|흥행|리뷰|review|논란|호불호)\b", "evaluation"),

    # --- production ---
    (
        r"\b(?:제작(?!\s*진|진)|스태프|staff|방영(?!\s*목록)|"
        r"방송|원작|판권|배급|성우진|성우|감독|각본|작화)\b",
        "production",
    ),

    # --- episode ---
    (
        r"\b(?:에피소드|episode|ep\.|회차|방영\s*목록|방영목록|방송\s*목록|"
        r"화\s*수|episodes?)\b",
        "episode",
    ),

    # --- worldview / setting / concept (worldview is the most specific) ---
    (r"\b(?:세계관|worldview|world\s*view)\b", "worldview"),
    (
        r"\b(?:설정|용어|기술(?!\s*스태프)|능력|스킬|skill|magic|마법|"
        r"system|시스템|밸런스)\b",
        "setting",
    ),
    (r"\b(?:컨셉|concept|개념|테마|theme)\b", "concept"),

    # --- trivia ---
    (r"\b(?:기타|여담|trivia|미스|오류|이스터에그|easter\s*egg)\b", "trivia"),
)

# Compile patterns once. The rule table stays public so tests can also
# exercise the *raw* patterns if they want.
_COMPILED_PATTERNS: List[Tuple[re.Pattern, SectionType]] = [
    (re.compile(p, re.IGNORECASE), t) for p, t in SECTION_TYPE_PATTERNS
]


# When the heading is a generic content marker (``본문``, ``요약 본문`` etc.)
# we have no real signal, so we fall back to the page-level ``relation`` hint.
_RELATION_HINT_TO_TYPE = {
    "main": "summary",
    "character": "character",
    "setting": "setting",
    "plot": "synopsis",
    "review": "evaluation",
    "production": "production",
    "episode": "episode",
    "other": "other",
}


def _join_for_match(heading_path: Iterable[str]) -> str:
    parts = [normalize_text_for_id(p) for p in heading_path if p and str(p).strip()]
    return " > ".join(parts)


def classify_section_type(
    heading_path: Sequence[str],
    *,
    page_relation: Optional[str] = None,
) -> SectionType:
    """Return the best-matching ``SectionType`` for ``heading_path``.

    ``page_relation`` is a soft hint used only when the heading itself is too
    generic to classify (e.g. ``"본문"``). It must be one of the values in
    :data:`eval.harness.dataset_v4_schema.RELATIONS` or ``None``.
    """
    text = _join_for_match(heading_path)
    if not text:
        text = ""
    for pattern, kind in _COMPILED_PATTERNS:
        if pattern.search(text):
            return kind

    # Generic heading: defer to relation hint when present.
    if page_relation:
        hinted = _RELATION_HINT_TO_TYPE.get(page_relation)
        if hinted:
            return hinted  # type: ignore[return-value]

    return "other"
