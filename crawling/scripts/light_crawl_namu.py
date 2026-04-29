"""Light-weight namu.wiki crawler for Phase 5 audit *demos only*.

================================================================
                ⚠  DEMO / SMOKE-TEST CRAWLER  ⚠
================================================================

DO NOT USE THIS SCRIPT FOR PRODUCTION RE-CRAWLS OR DATASET GENERATION.

This script exists so the audit harness can be exercised on a tiny
corpus (~10 pages) without standing up Selenium / MySQL / MongoDB. It
deliberately skips most of what makes ``crawl_namu.py`` correct:

    * No character/subpage link discovery — every page is a flat root.
    * No multi-process workers / no DB persistence.
    * Section extraction is a single-pass h2 walk with a wholesale-body
      fallback. **All pages tend to collapse to one ``본문`` section**,
      which is why the audit harness will (correctly) flag the demo
      output:
          - mean section_count < 1.5  (Phase 5.1 warning)
          - section_type 100% summary (Phase 5.1 summary skew warning)
          - generic single-segment heading (Phase 5.1 heading warning)
      Those warnings are expected on this script's output and do **not**
      reflect a bug in the audit code.
    * Section heading fidelity is intentionally low; section_type
      classification will collapse onto ``summary``.

Use ``crawl_namu.py`` for production re-crawls. The Phase 5.1 wrapper
``scripts.run_namu_crawl_v4_pipeline`` consumes the v3 JSONL produced by
``crawl_namu.py``; pointing it at ``light_crawl_namu`` output will fail
the audit gate (``--fail-on-warning``) and that is the intended
behaviour, not a regression.

Pipeline order (when this script is used purely as a smoke fixture)::

    light_crawl_namu --> convert_namu_v3_to_v4 --> export_rag_chunks
        --> build_split_manifest --> build_sft_datasets --> audit_crawl_v4

Usage (demo only)::

    python -m scripts.light_crawl_namu \\
        --seeds 귀멸의 칼날 \\
        --seeds 진격의 거인 \\
        --out data/light_crawl_v3.jsonl

    # or read seeds from a JSON file (list of strings, or a quarter-keyed dict)
    python -m scripts.light_crawl_namu \\
        --seed-file data/seeds.json --limit 10 --out data/light_crawl_v3.jsonl
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


BASE_URL = "https://namu.wiki"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/147.0.0.0 Safari/537.36"
)

# Same noise patterns crawl_namu.py uses, condensed. We keep this list
# short — heavier cleaning happens later in clean_text / Phase 1.
_NOISE_PATTERNS = [
    r"\[편집\]",
    r"^\s*\d+(?:\.\d+)*\.\s+",  # leading "1." / "1.2." numbering
]
_NOISE_RE = re.compile("|".join(_NOISE_PATTERNS), flags=re.MULTILINE)


def _heading_text(h: Tag) -> str:
    raw = h.get_text(" ", strip=True)
    cleaned = _NOISE_RE.sub("", raw).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned


def _section_text(start: Tag, stop_tags: Tuple[str, ...]) -> str:
    """Concat text from siblings of ``start`` up to the next ``stop_tags`` heading.

    Tables and list items are joined with newlines, bare paragraphs with
    blank-line separators. Anchors and edit links are filtered out.
    """
    parts: List[str] = []
    for sib in start.next_siblings:
        if isinstance(sib, NavigableString):
            text = str(sib).strip()
            if text:
                parts.append(text)
            continue
        if not isinstance(sib, Tag):
            continue
        if sib.name in stop_tags:
            break
        # Skip empty / decorative blocks
        text = sib.get_text(" ", strip=True)
        if not text:
            continue
        parts.append(text)
    body = "\n\n".join(parts)
    body = _NOISE_RE.sub("", body)
    body = re.sub(r"[ \t]+", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _split_into_chunks(text: str, *, max_chars: int = 800) -> List[str]:
    """Split a section's text into roughly ``max_chars``-sized paragraph
    groups. Mirrors the heuristic used in ``namu_v3_to_v4._split_paragraphs``
    so downstream chunking stays consistent.
    """
    if not text:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for p in paragraphs:
        if buf_len + len(p) + 2 <= max_chars or not buf:
            buf.append(p)
            buf_len += len(p) + 2
        else:
            chunks.append("\n\n".join(buf))
            buf = [p]
            buf_len = len(p)
    if buf:
        chunks.append("\n\n".join(buf))
    # Hard-split overly long single paragraphs.
    out: List[str] = []
    for c in chunks:
        if len(c) <= max_chars * 1.5:
            out.append(c)
        else:
            for i in range(0, len(c), max_chars):
                out.append(c[i : i + max_chars])
    return out


def _extract_canonical_url(soup: BeautifulSoup) -> Optional[str]:
    link = soup.find("link", rel="canonical")
    if link and link.get("href"):
        return link.get("href")
    og = soup.find("meta", property="og:url")
    if og and og.get("content"):
        return og.get("content")
    return None


def _extract_aliases(soup: BeautifulSoup) -> List[str]:
    """Best-effort alias extraction from namu.wiki redirect / synonym links."""
    aliases: List[str] = []
    desc = soup.find("meta", property="og:description")
    if desc and desc.get("content"):
        # namu.wiki sometimes lists aliases right after the title in the
        # description: "X — 일본 만화. 영어로 X-Y. 별명 Z." We don't try to
        # parse them out here; aliases stay empty by default and the
        # audit will surface that gap.
        pass
    return aliases


def fetch_page(seed_title: str, *, sleep: float = 1.5) -> Optional[Dict[str, Any]]:
    """Fetch a single namu.wiki page and shape it into a v3-rich record.

    Returns ``None`` when the page is unreachable / empty.
    """
    encoded = quote(seed_title, safe="")
    url = f"{BASE_URL}/w/{encoded}"
    headers = {"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6"}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as e:
        print(f"[fetch] {seed_title}: {e}", file=sys.stderr)
        return None
    if resp.status_code != 200:
        print(f"[fetch] {seed_title}: HTTP {resp.status_code}", file=sys.stderr)
        return None
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "html.parser")

    og_title = soup.find("meta", property="og:title")
    title = (og_title.get("content").strip() if og_title and og_title.get("content") else seed_title)

    # Walk h2 headings -> section_order; for each h2, capture text up to
    # the next h2 (skip h3/h4 splitting for the light demo).
    sections: Dict[str, Dict[str, Any]] = {}
    section_order: List[str] = []
    headings = soup.find_all("h2")
    for h in headings:
        name = _heading_text(h)
        if not name or len(name) > 50:
            continue
        body = _section_text(h, stop_tags=("h2",))
        if not body or len(body) < 60:
            continue
        if name in sections:
            continue
        chunks = _split_into_chunks(body, max_chars=800)
        sections[name] = {
            "text": body,
            "chunks": chunks,
            "urls": [url],
            "model": None,
            "ts": None,
        }
        section_order.append(name)

    if not sections:
        # As a last resort, dump the article body wholesale into "본문".
        article_text = soup.get_text("\n", strip=True)
        if len(article_text) >= 200:
            article_text = _NOISE_RE.sub("", article_text)
            sections["본문"] = {
                "text": article_text,
                "chunks": _split_into_chunks(article_text, max_chars=800),
                "urls": [url],
                "model": None,
                "ts": None,
            }
            section_order.append("본문")

    record = {
        "seed": seed_title,
        "title": title,
        "url": url,
        "canonical_url": _extract_canonical_url(soup) or url,
        "aliases": _extract_aliases(soup),
        "sections": sections,
        "section_order": section_order,
        "meta": {
            "seed_title": seed_title,
            "depth": 0,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
        "subpages": [],
        "summary": "",
        "sum_bullets": [],
    }
    if sleep > 0:
        time.sleep(sleep)
    return record


def _load_seeds(args: argparse.Namespace) -> List[str]:
    seeds: List[str] = []
    if args.seeds:
        seeds.extend(args.seeds)
    if args.seed_file:
        with Path(args.seed_file).open("r", encoding="utf-8") as f:
            obj = json.load(f)
        if isinstance(obj, list):
            for item in obj:
                if isinstance(item, str):
                    seeds.append(item)
        elif isinstance(obj, dict):
            # quarter-keyed dict like seed_titles.test.json
            for v in obj.values():
                if isinstance(v, list):
                    seeds.extend(s for s in v if isinstance(s, str))
    # de-dup while preserving order
    out: List[str] = []
    seen = set()
    for s in seeds:
        s = s.strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    if args.limit:
        out = out[: args.limit]
    return out


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "DEMO-ONLY lightweight namu.wiki crawler. Output is v3-rich "
            "JSONL intended for the Phase 5 audit harness smoke test. "
            "Section extraction is intentionally low-fidelity (every page "
            "tends to collapse to a single body section) so output of "
            "this script SHOULD trigger Phase 5.1 audit warnings such as "
            "'mean section_count < 1.5' and 'summary section_type owns "
            "100%'. Use crawl_namu.py for production crawls."
        )
    )
    p.add_argument(
        "--seeds",
        action="append",
        default=[],
        help="seed title (repeat --seeds for multiple titles)",
    )
    p.add_argument(
        "--seed-file",
        default=None,
        help="JSON file with a list[str] of titles or a quarter-keyed dict",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap on the number of seeds (after de-dup)",
    )
    p.add_argument(
        "--sleep",
        type=float,
        default=1.5,
        help="seconds to sleep between page fetches (default: %(default)s)",
    )
    p.add_argument(
        "--out", required=True, help="output path for the v3-rich JSONL"
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    seeds = _load_seeds(args)
    if not seeds:
        print("no seeds provided (use --seeds or --seed-file)", file=sys.stderr)
        return 2

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    success = 0
    failed: List[Tuple[str, str]] = []
    with out_path.open("w", encoding="utf-8") as f:
        for seed in seeds:
            print(f"[fetch] {seed}", file=sys.stderr)
            record = fetch_page(seed, sleep=args.sleep)
            if record is None:
                failed.append((seed, "fetch failed"))
                continue
            if not record["sections"]:
                failed.append((seed, "no sections extracted"))
                continue
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            success += 1

    print(f"crawled {success}/{len(seeds)} seeds -> {out_path}")
    if failed:
        for seed, reason in failed:
            print(f"  failed: {seed} ({reason})", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
