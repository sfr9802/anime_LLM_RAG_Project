from __future__ import annotations

"""Utility helpers for the RAG service."""

from typing import Any, Dict, List
import os
import re
import unicodedata

from app.app.configure import config


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return re.sub(r"[\s\W_]+", "", s, flags=re.UNICODE)


_DEFAULT_ALIAS_MAP = {
    "방도리": ["BanG Dream!", "bang dream", "bandori", "girls band party", "bangdream"],
    "귀칼": ["귀멸의 칼날"],
    "5등분의 신부": [
        "오등분의 신부",
        "The Quintessential Quintuplets",
        "5-toubun no hanayome",
        "五等分の花嫁",
    ],
}
_ALIAS_MAP = getattr(config, "ALIAS_MAP", None) or _DEFAULT_ALIAS_MAP


def _expand_queries(q: str) -> List[str]:
    out = [q]
    # NOTE: normalized/no-space query is usually harmful for dense retrieval.
    # Keep it behind a flag for sparse / debugging use.
    if os.getenv("RAG_USE_NORM_QUERY", "0").lower() in ("1", "true", "yes"):
        nq = _norm(q)
        if nq and nq != q:
            out.append(nq)
    for k, vs in _ALIAS_MAP.items():
        if k in q:
            out.extend(vs)
    uniq, seen = [], set()
    for s in out:
        s = (s or "").strip()
        if len(s) < 2:
            continue
        if s in seen:
            continue
        seen.add(s)
        uniq.append(s)
    return uniq


def _title_from_meta(meta: Dict[str, Any]) -> str:
    return meta.get("seed_title") or meta.get("parent") or meta.get("title") or ""


def _cap_by_title(items: List[Dict[str, Any]], cap: int = 2) -> List[Dict[str, Any]]:
    if cap <= 0 or not items:
        return items
    cnt: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for it in items:
        meta = it.get("metadata") or {}
        title = meta.get("seed_title") or meta.get("parent") or meta.get("title") or ""
        c = cnt.get(title, 0)
        if c < cap:
            out.append(it)
            cnt[title] = c + 1
    return out


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def _env_ints(name: str, default: List[int]) -> List[int]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    toks = [t.strip() for t in raw.replace(";", ",").split(",")]
    out: List[int] = []
    for t in toks:
        if not t:
            continue
        try:
            out.append(int(t))
        except Exception:
            pass
    out = sorted(set(out))
    return out or list(default)


__all__ = [
    "_expand_queries",
    "_title_from_meta",
    "_cap_by_title",
    "_env_int",
    "_env_float",
    "_env_ints",
]

