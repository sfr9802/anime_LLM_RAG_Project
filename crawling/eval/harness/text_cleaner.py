"""Defensive text cleaning + per-section quality probe.

The converter stores **both** ``raw_text`` (preserved exactly as received)
and ``clean_text`` (after the cleanup applied here). Cleanup is intentionally
conservative — proper nouns, character names, and Korean particles must
survive — so this module only removes patterns that are very obviously
namu.wiki UI residue:

* footnote / reference markers like ``[1]``, ``[*]``, ``[주]``
* edit-trace markers like ``[편집]``, ``[수정]``, leftover ``펼치기 · 접기``
* control characters and zero-width spaces
* duplicated paragraphs that would otherwise pollute chunks
* runs of whitespace collapsed to a single space (newlines preserved as
  paragraph breaks)

The quality probe inspects ``clean_text`` and returns a
:class:`SectionQuality` with cheap heuristic flags so downstream
filters / RAG indexing can quickly drop stubs and table dumps.
"""

from __future__ import annotations

import re
import unicodedata
from typing import List

from .dataset_v4_schema import SectionQuality


STUB_THRESHOLD = 60  # chars; clean_text shorter than this is flagged is_stub
TABLE_PIPE_RATIO = 0.012  # pipes per char above this -> is_table_like
TABLE_BAR_HINT = 6  # consecutive — / ─ / = chars on a line marks table separators
LIST_LINE_RATIO = 0.55  # share of lines starting with bullets/numbers -> is_list_like


_FOOTNOTE_RE = re.compile(r"\[(?:\s*\d+\s*|\s*\*\s*|\s*주(?:\s*\d+)?\s*)\]")
_EDITTRACE_RE = re.compile(
    r"\[(?:편집|수정|원본|위키 ?편집|edit)\]",
    re.IGNORECASE,
)
_TOGGLE_RESIDUE_RE = re.compile(
    r"(?:펼치기\s*[·•・/]\s*접기|접기\s*[·•・/]\s*펼치기|\[펼치기\]|\[접기\])",
)
_ZW_RE = re.compile(r"[​-‏﻿⁠]")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

_BULLET_LINE_RE = re.compile(r"^\s*(?:[-*•·▪◦●○]|\d+[.)]|[가-힣]\.|[a-z]\))\s+", re.IGNORECASE)

_SPOILER_MARKERS = (
    "스포일러",
    "spoiler",
    "[스포일러]",
    "결말 주의",
    "결말 누설",
    "스포 주의",
)


def _normalize_whitespace(text: str) -> str:
    """Collapse intra-line whitespace but preserve paragraph (blank-line) breaks."""
    # Normalize line endings first.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    out_lines: List[str] = []
    for line in text.split("\n"):
        # Collapse runs of whitespace within the line, then strip.
        cleaned_line = re.sub(r"[ \t 　\f\v]+", " ", line).strip()
        out_lines.append(cleaned_line)
    # Collapse runs of >2 blank lines to a single blank line (paragraph break).
    joined = "\n".join(out_lines)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


def _dedupe_paragraphs(text: str) -> str:
    """Drop consecutive duplicate paragraphs (a frequent namu.wiki copy-paste pattern)."""
    if not text:
        return text
    paras = re.split(r"\n\s*\n", text)
    out: List[str] = []
    for p in paras:
        p_norm = re.sub(r"\s+", " ", p).strip()
        if not p_norm:
            continue
        if out:
            prev = re.sub(r"\s+", " ", out[-1]).strip()
            if prev == p_norm:
                continue
        out.append(p.strip())
    return "\n\n".join(out)


def clean_text(raw_text: str) -> str:
    """Conservative cleanup. Returns ``""`` when input is falsy."""
    if not raw_text:
        return ""
    text = unicodedata.normalize("NFKC", raw_text)
    text = _ZW_RE.sub("", text)
    text = _CONTROL_RE.sub("", text)
    text = _FOOTNOTE_RE.sub("", text)
    text = _EDITTRACE_RE.sub("", text)
    text = _TOGGLE_RESIDUE_RE.sub("", text)
    text = _normalize_whitespace(text)
    text = _dedupe_paragraphs(text)
    return text


def _is_table_like(text: str) -> bool:
    if not text:
        return False
    pipes = text.count("|") + text.count("┃") + text.count("│")
    if len(text) > 0 and pipes / len(text) >= TABLE_PIPE_RATIO:
        return True
    # ASCII table separator lines like ----- or =====
    for line in text.split("\n"):
        s = line.strip()
        if len(s) >= TABLE_BAR_HINT and (
            set(s) <= {"-", "─", "—", "=", "+"} and len(set(s)) <= 3
        ):
            return True
    return False


def _is_list_like(text: str) -> bool:
    if not text:
        return False
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) < 3:
        return False
    bullet_lines = sum(1 for ln in lines if _BULLET_LINE_RE.match(ln))
    return bullet_lines / len(lines) >= LIST_LINE_RATIO


def _has_spoiler(text: str) -> bool:
    if not text:
        return False
    head = text[:300].lower()
    return any(m.lower() in head for m in _SPOILER_MARKERS)


def section_quality(
    raw_text: str,
    cleaned: str,
    *,
    stub_threshold: int = STUB_THRESHOLD,
) -> SectionQuality:
    """Probe heuristic quality flags on ``cleaned``.

    ``noise_score`` = ``1 - len(cleaned)/len(raw_text)`` clipped to [0, 1].
    A score of ~0 means cleanup removed almost nothing; ~1 means cleanup
    removed almost everything (very noisy input).
    """
    text_len = len(cleaned or "")
    raw_len = len(raw_text or "")
    if raw_len > 0:
        noise = 1.0 - (text_len / raw_len)
    else:
        noise = 0.0
    if noise < 0.0:
        noise = 0.0
    elif noise > 1.0:
        noise = 1.0

    return SectionQuality(
        text_length=text_len,
        noise_score=round(noise, 4),
        is_stub=text_len < stub_threshold,
        has_spoiler=_has_spoiler(cleaned or raw_text or ""),
        is_table_like=_is_table_like(cleaned or ""),
        is_list_like=_is_list_like(cleaned or ""),
    )
