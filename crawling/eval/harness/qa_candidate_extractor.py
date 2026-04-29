"""Phase 4 — rule-based QA candidate extractor.

Generates a single :class:`QACandidate` from a chunk-like input
(``RagChunkV4`` dict) using only ``section_type`` / ``title`` /
``chunk_text``. There are intentionally no LLM calls — Phase 4's goal
is to validate the SFT export pipeline, not to maximise QA quality.

Design principles (Phase 4 spec §3 ``qa_candidate_extractor.py``):

* When the rule cannot ground an answer in chunk text, return ``None``
  rather than inventing one.
* The returned ``evidence_span`` MUST be a verbatim substring of
  ``chunk_text`` so downstream callers can trust ``evidence_span in
  chunk_text``.
* The answer is the same verbatim substring — without an LLM we cannot
  paraphrase faithfully, and a short literal answer is preferable to a
  fabricated one.
"""

from __future__ import annotations

from typing import Optional, Tuple

from .dataset_v4_schema import QACandidate, SectionType


# Section_type -> Korean question template. Keep these one-line direct
# questions; richer phrasing belongs in a future LLM-backed extractor.
QUESTION_TEMPLATES_BY_SECTION = {
    "summary": "{title}의 개요를 알려줘.",
    "synopsis": "{title}의 줄거리를 설명해줘.",
    "character": "{title}에 등장하는 인물에 대해 알려줘.",
    "setting": "{title}의 설정에 대해 설명해줘.",
    "worldview": "{title}의 세계관에 대해 알려줘.",
    "concept": "{title}의 핵심 개념을 설명해줘.",
    "episode": "{title}의 에피소드를 알려줘.",
    "evaluation": "{title}에 대한 평가를 알려줘.",
    "production": "{title}의 제작 정보를 알려줘.",
    "music": "{title}의 음악에 대해 알려줘.",
    "trivia": "{title}에 관한 여담을 알려줘.",
}

# Korean and English sentence terminators we accept as a "first-sentence"
# boundary when building evidence_span.
_SENTENCE_TERMINATORS: Tuple[str, ...] = (".", "!", "?", "。", "\n")

# Sane defaults for evidence span extraction. ``min_evidence_chars`` is
# the smallest acceptable evidence span — going lower yields fragments
# like "그." that are useless as answers. ``max_evidence_chars`` caps a
# runaway sentence (a paragraph with no terminator) at a tractable size.
DEFAULT_MIN_EVIDENCE_CHARS = 30
DEFAULT_MAX_EVIDENCE_CHARS = 400


def supported_section_types() -> Tuple[str, ...]:
    """Return the section_types that the rule extractor knows how to question."""
    return tuple(QUESTION_TEMPLATES_BY_SECTION.keys())


def first_evidence_span(
    text: str,
    *,
    min_chars: int = DEFAULT_MIN_EVIDENCE_CHARS,
    max_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
) -> str:
    """Return the first sentence-like verbatim substring of ``text``.

    Walks ``text`` from the start and stops at the first sentence
    terminator that appears at or after ``min_chars``. If no terminator
    is found, returns up to ``max_chars`` of the trimmed text.

    The returned span is always a substring of ``text.strip()``, so the
    caller can assert ``span in text`` (after the same strip).
    """
    if not isinstance(text, str):
        return ""
    s = text.strip()
    if not s:
        return ""

    end = -1
    for i, ch in enumerate(s):
        if ch in _SENTENCE_TERMINATORS and i >= min_chars:
            end = i + 1
            break
    if end == -1:
        candidate = s[:max_chars]
    else:
        candidate = s[:end]
    candidate = candidate.strip()
    if len(candidate) > max_chars:
        candidate = candidate[:max_chars].strip()
    return candidate


def extract_qa_candidate(
    *,
    title: str,
    section_type: str,
    chunk_text: str,
    min_chars: int = 60,
    min_evidence_chars: int = DEFAULT_MIN_EVIDENCE_CHARS,
    max_evidence_chars: int = DEFAULT_MAX_EVIDENCE_CHARS,
) -> Optional[QACandidate]:
    """Build a single rule-based QA candidate from a chunk.

    Returns ``None`` (i.e. the chunk should be skipped) when:
      * ``title`` is missing/blank
      * ``chunk_text`` is shorter than ``min_chars``
      * ``section_type`` is not in :data:`QUESTION_TEMPLATES_BY_SECTION`
      * the first-sentence span cannot be extracted, or is not a true
        substring of the trimmed chunk_text
    """
    if not isinstance(title, str) or not title.strip():
        return None
    if not isinstance(chunk_text, str) or len(chunk_text) < min_chars:
        return None
    template = QUESTION_TEMPLATES_BY_SECTION.get(section_type)
    if template is None:
        return None
    evidence_span = first_evidence_span(
        chunk_text,
        min_chars=min_evidence_chars,
        max_chars=max_evidence_chars,
    )
    if not evidence_span:
        return None
    # Defensive: keep callers' "evidence_span in chunk_text" invariant
    # even after our internal strip(), by checking against the trimmed
    # source the same way.
    if evidence_span not in chunk_text.strip():
        return None
    question = template.format(title=title.strip())
    return QACandidate(
        question=question,
        answer=evidence_span,
        evidence_span=evidence_span,
        difficulty="easy",
        answer_type="fact",
    )
