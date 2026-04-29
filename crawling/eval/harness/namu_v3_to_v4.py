"""Convert v3 namu_anime JSONL records into v4 page/chunk records.

The v3 records have a few structural problems we fix here:

  * ``title`` is sometimes a generic section name (``등장인물``, ``설정``, ...)
    rather than the work name. v4 separates ``work_title``, ``page_title``,
    ``page_type``, and ``relation`` so the work identity is recovered from
    ``meta.seed_title`` / ``seed`` whenever ``title`` is generic.
  * ``subpages`` carries character / setting documents inline. v4 promotes
    every subpage entry into its own page so retrieval can address them
    independently.
  * Source text and the LLM-generated summary live in the same ``요약``
    section in v3. v4 routes the generated summary into ``generated_summary``
    and excludes that section from chunk generation, while still keeping the
    source ``본문`` / ``등장인물`` / ``설정`` sections.

The converter is defensive: malformed records become warnings rather than
exceptions so a single bad row never kills a full migration.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

from .dataset_v4_schema import (
    GENERIC_TITLES,
    PAGE_TYPES,
    SCHEMA_VERSION_CHUNK,
    SCHEMA_VERSION_PAGE,
    ChunkQuality,
    ChunkV4,
    DocumentQuality,
    GeneratedSummary,
    PageCrawl,
    PageSource,
    PageType,
    PageV4,
    Relation,
    SectionV4,
    build_text_for_embedding,
    estimate_tokens,
    is_generic_title,
    join_section_path,
    make_section_key,
    normalize_section_path,
    page_type_from_relation,
    relation_from_subpage_key,
    sha1_id,
    title_from_url,
)
from .section_classifier import classify_section_type
from .text_cleaner import clean_text, section_quality


SHORT_CHUNK_THRESHOLD = 60  # chars; below this we mark is_short=True
LONG_PARAGRAPH_THRESHOLD = 1500  # chars; above this we sentence-split raw_text
TARGET_GROUPED_CHUNK_CHARS = 800  # target size when grouping sentences
GENERATED_SUMMARY_SECTION_KEY = "요약"
DEFAULT_BODY_HEADING = "본문"

# Substrings that indicate the namu.wiki page header/UI is still in the text
# (i.e. the boilerplate filter that ran on root sections did not run here).
_BOILERPLATE_MARKERS = (
    "최근 수정 시각",
    "편집 토론 역사",
    "분류 상위 문서",
)


def _looks_boilerplated(text: str) -> bool:
    head = text[:120]
    return any(m in head for m in _BOILERPLATE_MARKERS)


def _iter_jsonl(path: Path) -> Iterator[Tuple[int, Dict[str, Any]]]:
    """Yield (line_number, parsed_object) pairs. Skips empty / unparseable lines."""
    with path.open("r", encoding="utf-8") as f:
        for i, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield i, json.loads(line)
            except json.JSONDecodeError:
                continue


def _first_url(section: Dict[str, Any]) -> Optional[str]:
    urls = section.get("urls") or []
    if isinstance(urls, list) and urls:
        v = urls[0]
        if isinstance(v, str) and v:
            return v
    return None


def _resolve_work_title(record: Dict[str, Any]) -> Tuple[str, List[str]]:
    """Return (work_title, warnings).

    Priority:
        1. ``meta.seed_title`` (most reliable)
        2. top-level ``seed``
        3. top-level ``title`` if not generic
        4. URL-derived title from any ``urls`` list
        5. ``"unknown"`` (with warning)
    """
    warnings: List[str] = []
    meta = record.get("meta") or {}
    candidates: List[str] = []
    for key, src in (
        ("meta.seed_title", meta.get("seed_title")),
        ("seed", record.get("seed")),
        ("title", record.get("title")),
    ):
        if isinstance(src, str) and src.strip():
            candidates.append(src.strip())

    for cand in candidates:
        if not is_generic_title(cand):
            return cand, warnings

    # all candidates are generic or missing; try URL fallback from any section
    sections = record.get("sections") or {}
    if isinstance(sections, dict):
        for sec in sections.values():
            if isinstance(sec, dict):
                u = _first_url(sec)
                if u:
                    t = title_from_url(u)
                    if t:
                        # URL trailing segment is usually "<work>/<sub>"; take head
                        head = t.split("/", 1)[0]
                        if head and not is_generic_title(head):
                            warnings.append(
                                f"work_title recovered from URL ({u}) -> {head!r}"
                            )
                            return head, warnings

    if candidates:
        warnings.append(
            f"work_title fell back to generic candidate {candidates[0]!r}"
        )
        return candidates[0], warnings
    warnings.append("work_title is missing; using 'unknown'")
    return "unknown", warnings


def _root_canonical_url(record: Dict[str, Any]) -> Optional[str]:
    """Pick a canonical URL for the root page from v3 sections."""
    sections = record.get("sections") or {}
    if not isinstance(sections, dict):
        return None
    # Prefer "본문" then any non-empty URL
    body = sections.get(DEFAULT_BODY_HEADING)
    if isinstance(body, dict):
        u = _first_url(body)
        if u:
            return u
    for sec in sections.values():
        if isinstance(sec, dict):
            u = _first_url(sec)
            if u:
                return u
    return None


def _generated_summary_from_record(record: Dict[str, Any]) -> GeneratedSummary:
    """Pull LLM-generated summary content out of v3 fields.

    v3 stores generated summary in three overlapping places:
        - top-level ``summary`` (string)
        - top-level ``sum_bullets`` / ``summary_bullets``
        - ``sections["요약"]`` with ``text`` + ``bullets`` + ``model`` + ``ts``

    We prefer ``sections["요약"]`` because it carries model + timestamp.
    """
    sections = record.get("sections") or {}
    summary_section = sections.get(GENERATED_SUMMARY_SECTION_KEY) if isinstance(sections, dict) else None

    text: Optional[str] = None
    bullets: List[str] = []
    model: Optional[str] = None
    created_at: Optional[str] = None

    if isinstance(summary_section, dict):
        t = summary_section.get("text")
        if isinstance(t, str) and t.strip():
            text = t.strip()
        b = summary_section.get("bullets")
        if isinstance(b, list):
            bullets = [str(x) for x in b if isinstance(x, str) and x.strip()]
        m = summary_section.get("model")
        if isinstance(m, str) and m.strip():
            model = m.strip()
        ts = summary_section.get("ts")
        if isinstance(ts, str) and ts.strip():
            created_at = ts.strip()

    if not text:
        top = record.get("summary")
        if isinstance(top, str) and top.strip():
            text = top.strip()

    if not bullets:
        for key in ("sum_bullets", "summary_bullets"):
            v = record.get(key)
            if isinstance(v, list) and v:
                bullets = [str(x) for x in v if isinstance(x, str) and x.strip()]
                if bullets:
                    break

    if not created_at:
        ca = record.get("created_at")
        if isinstance(ca, str) and ca.strip():
            created_at = ca.strip()

    return GeneratedSummary(
        model=model,
        text=text,
        bullets=bullets,
        created_at=created_at,
    )


def _section_chunk_texts(section: Dict[str, Any]) -> List[str]:
    """Pick the best chunk-level texts for a v3 section.

    Falls back to ``text`` as a single chunk when ``chunks`` is missing/empty.
    """
    chunks = section.get("chunks")
    if isinstance(chunks, list):
        out = [c for c in chunks if isinstance(c, str) and c.strip()]
        if out:
            return [c.strip() for c in out]
    text = section.get("text")
    if isinstance(text, str) and text.strip():
        return [text.strip()]
    return []


def _section_links(section: Dict[str, Any]) -> List[str]:
    urls = section.get("urls") or []
    if isinstance(urls, list):
        return [u for u in urls if isinstance(u, str) and u]
    return []


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)\s+|(?<=요\.)\s+")


def _split_sentences(text: str) -> List[str]:
    """Split text on Korean/English sentence boundaries.

    Falls back to the whole text when no boundary is found, so callers can
    still emit a single (long) chunk and flag it for downstream review.
    """
    if not text:
        return []
    parts = _SENTENCE_SPLIT_RE.split(text)
    return [p.strip() for p in parts if p and p.strip()]


def _group_to_target(sentences: List[str], target: int) -> List[str]:
    """Greedily group adjacent sentences into chunks of ~target chars."""
    if not sentences:
        return []
    out: List[str] = []
    buf: List[str] = []
    buf_len = 0
    for s in sentences:
        s_len = len(s) + 1
        if buf and buf_len + s_len > target:
            out.append(" ".join(buf).strip())
            buf = [s]
            buf_len = s_len
        else:
            buf.append(s)
            buf_len += s_len
    if buf:
        out.append(" ".join(buf).strip())
    return [c for c in out if c]


def _hard_split(text: str, target: int) -> List[str]:
    """Last-resort splitter for blobs with no sentence boundaries (tables, lists).

    Splits at ~target chars, preferring whitespace breakpoints when one is
    available within +/- 10% of the target.
    """
    out: List[str] = []
    n = len(text)
    if n == 0:
        return out
    i = 0
    window = max(1, target)
    slack = max(1, window // 10)
    while i < n:
        end = min(n, i + window)
        if end < n:
            cut = text.rfind(" ", max(i, end - slack), end)
            if cut <= i:
                cut = end
            else:
                cut = cut + 1  # consume the space
        else:
            cut = end
        piece = text[i:cut].strip()
        if piece:
            out.append(piece)
        i = cut
    return out


def _split_paragraphs(text: str) -> List[str]:
    """Split a raw_text body into chunk-sized pieces.

    Strategy:
        1. Split by blank-line paragraphs.
        2. Any paragraph longer than LONG_PARAGRAPH_THRESHOLD is split into
           sentences and re-grouped to ~TARGET_GROUPED_CHUNK_CHARS each.
        3. As a last resort, hard-split anything still too long (e.g. tabular
           dumps with no sentence terminators) at whitespace boundaries.
    """
    if not text:
        return []
    parts = re.split(r"\n\s*\n+", text)
    out: List[str] = []
    hard_limit = max(LONG_PARAGRAPH_THRESHOLD, TARGET_GROUPED_CHUNK_CHARS) * 2
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if len(p) <= LONG_PARAGRAPH_THRESHOLD:
            out.append(p)
            continue
        sentences = _split_sentences(p)
        grouped = _group_to_target(sentences, TARGET_GROUPED_CHUNK_CHARS) if sentences else []
        candidates = grouped or [p]
        for c in candidates:
            if len(c) <= hard_limit:
                out.append(c)
            else:
                out.extend(_hard_split(c, TARGET_GROUPED_CHUNK_CHARS))
    return out


def _make_section(
    *,
    page_id: str,
    heading_path: List[str],
    order: int,
    text: str,
    links: List[str],
    depth: int = 1,
    occurrence: int = 0,
    page_relation: Optional[str] = None,
) -> SectionV4:
    """Build a SectionV4 with both legacy and Phase 1 fields populated.

    ``section_id`` keeps its v3->v4 formula (page_id+joined_path+order) so
    existing pipelines keep matching. ``section_key`` is the new
    order-stable identifier (page_id + normalized_path + occurrence).
    """
    section_id = sha1_id(page_id, join_section_path(heading_path), order)
    section_key = make_section_key(
        page_id=page_id,
        heading_path=heading_path,
        occurrence=occurrence,
    )
    raw_text = text or ""
    cleaned = clean_text(raw_text)
    quality = section_quality(raw_text, cleaned)
    section_type = classify_section_type(heading_path, page_relation=page_relation)
    return SectionV4(
        section_id=section_id,
        heading_path=heading_path,
        depth=depth,
        order=order,
        # ``text`` keeps backward-compat semantics: it equals the
        # post-cleanup text, just like in the previous v4 output. New
        # consumers should prefer ``clean_text`` for clarity.
        text=cleaned,
        links=links,
        section_key=section_key,
        section_type=section_type,
        raw_text=raw_text,
        clean_text=cleaned,
        quality=quality,
    )


def _make_chunks_for_section(
    *,
    page: PageV4,
    section: SectionV4,
    chunk_texts: List[str],
    base_chunk_index: int,
    fallback_url: Optional[str],
) -> Tuple[List[ChunkV4], int]:
    chunks: List[ChunkV4] = []
    next_idx = base_chunk_index
    section_url = section.links[0] if section.links else fallback_url
    for c_idx, text in enumerate(chunk_texts, start=base_chunk_index):
        text = text.strip()
        if not text:
            continue
        char_len = len(text)
        is_empty = char_len == 0
        is_short = char_len < SHORT_CHUNK_THRESHOLD
        chunk_id = sha1_id(page.page_id, section.section_id, c_idx, text[:200])
        chunk = ChunkV4(
            schema_version=SCHEMA_VERSION_CHUNK,
            chunk_id=chunk_id,
            page_id=page.page_id,
            work_id=page.work_id,
            work_title=page.work_title,
            page_title=page.page_title,
            page_type=page.page_type,
            relation=page.relation,
            section_path=list(section.heading_path),
            chunk_index=c_idx,
            text=text,
            text_for_embedding=build_text_for_embedding(
                work_title=page.work_title,
                page_title=page.page_title,
                page_type=page.page_type,
                relation=page.relation,
                section_path=section.heading_path,
                text=text,
            ),
            char_len=char_len,
            token_estimate=estimate_tokens(char_len),
            retrieval_tags=[],
            source_url=section_url,
            quality=ChunkQuality(
                is_empty=is_empty,
                is_short=is_short,
                is_truncated=False,
                boilerplate_removed=not _looks_boilerplated(text),
            ),
        )
        chunks.append(chunk)
        next_idx = c_idx + 1
    return chunks, next_idx


def _compute_document_quality(page: PageV4) -> DocumentQuality:
    """Roll up per-section quality flags into a page-level DocumentQuality.

    A section is "valid" when its clean_text is at least
    :data:`text_cleaner.STUB_THRESHOLD` characters and not flagged as a
    table/list. ``is_low_quality`` is True when the page has no valid
    sections at all so downstream filters can skip it cheaply.
    """
    total_len = 0
    valid = 0
    for sec in page.sections:
        total_len += sec.quality.text_length
        if (
            not sec.quality.is_stub
            and not sec.quality.is_table_like
            and not sec.quality.is_list_like
        ):
            valid += 1
    section_count = len(page.sections)
    is_low = section_count == 0 or valid == 0
    reason: Optional[str]
    if section_count == 0:
        reason = "no sections"
    elif valid == 0:
        reason = "all sections are stub/table/list"
    else:
        reason = None
    return DocumentQuality(
        total_text_length=total_len,
        section_count=section_count,
        valid_section_count=valid,
        is_low_quality=is_low,
        reason=reason,
    )


def _normalize_section_heading(
    heading: str,
    *,
    work_title: str,
    section_url: Optional[str],
) -> Tuple[str, List[str]]:
    """Return (heading, warnings).

    v3 occasionally stores a section under a heading equal to the work title
    while its URL points to ``/등장인물`` etc. In that case we rewrite the
    heading to the URL's tail segment so the section_path is meaningful.
    """
    warnings: List[str] = []
    h = (heading or "").strip()
    if not h:
        h = DEFAULT_BODY_HEADING
        warnings.append("section heading was empty; replaced with '본문'")
    if work_title and h.strip() == work_title.strip() and section_url:
        tail = title_from_url(section_url)
        if tail:
            sub = tail.split("/", 1)
            if len(sub) > 1 and sub[1]:
                h = sub[1]
                warnings.append(
                    f"section heading equal to work_title; rewrote to URL tail {h!r}"
                )
    return h, warnings


def _resolve_subpage_title(
    *,
    raw_title: Optional[str],
    url: Optional[str],
    work_title: str,
    relation: Relation,
) -> Tuple[str, List[str]]:
    """Pick a non-generic page_title for a subpage."""
    warnings: List[str] = []
    url_title = title_from_url(url)
    if url_title:
        # URL form is usually "<work>/<sub>" — keep the full thing as the page title
        if not is_generic_title(url_title):
            return url_title, warnings
    if isinstance(raw_title, str) and raw_title.strip():
        if not is_generic_title(raw_title):
            return raw_title.strip(), warnings
        # title is generic; fall through to fallback
    if url_title:
        warnings.append(
            f"subpage title generic; URL-derived title {url_title!r} also generic"
        )
        return url_title, warnings
    fallback = f"{work_title}/{relation}"
    warnings.append(f"subpage title missing; falling back to {fallback!r}")
    return fallback, warnings


def convert_record(
    record: Dict[str, Any],
    *,
    line_number: int = 0,
) -> Tuple[List[PageV4], List[ChunkV4], List[str]]:
    """Convert a single v3 record into v4 pages + chunks.

    Returns ``(pages, chunks, warnings)``. ``warnings`` is a list of human-readable
    diagnostic strings keyed loosely by line number for the validation report.
    """
    warnings: List[str] = []
    pages: List[PageV4] = []
    chunks: List[ChunkV4] = []

    if not isinstance(record, dict):
        warnings.append(f"line {line_number}: record is not a dict; skipped")
        return pages, chunks, warnings

    work_title, w_warns = _resolve_work_title(record)
    warnings.extend(f"line {line_number}: {w}" for w in w_warns)

    work_id = sha1_id(work_title)
    canonical_url = _root_canonical_url(record)

    meta = record.get("meta") or {}
    seed_title = meta.get("seed_title") if isinstance(meta, dict) else None
    fetched_at = meta.get("fetched_at") if isinstance(meta, dict) else None
    depth = int(meta.get("depth", 0) or 0) if isinstance(meta, dict) else 0

    # ---- root page ----
    root_relation: Relation = "main"
    root_page_type: PageType = "work"
    root_page_title = work_title
    if is_generic_title(record.get("title")):
        warnings.append(
            f"line {line_number}: v3 title {record.get('title')!r} is generic; "
            f"using work_title {work_title!r} for root page_title"
        )

    root_page_id = sha1_id(canonical_url or "", work_title, root_page_title, root_relation)

    root_page = PageV4(
        schema_version=SCHEMA_VERSION_PAGE,
        page_id=root_page_id,
        work_id=work_id,
        work_title=work_title,
        page_title=root_page_title,
        page_type=root_page_type,
        relation=root_relation,
        canonical_url=canonical_url,
        parent_url=None,
        aliases=[],
        categories=[],
        source=PageSource(site="namu.wiki", fetched_at=fetched_at, revision_time=None),
        crawl=PageCrawl(
            seed_title=seed_title if isinstance(seed_title, str) else None,
            depth=depth,
            discovery_reason="root",
            parent_page_id=None,
        ),
        sections=[],
        generated_summary=_generated_summary_from_record(record),
    )

    # ---- root sections + chunks ----
    sections = record.get("sections") or {}
    section_order = record.get("section_order") or []
    if not isinstance(section_order, list) or not section_order:
        section_order = list(sections.keys()) if isinstance(sections, dict) else []

    section_index = 0
    chunk_index = 0
    root_path_seen: Counter = Counter()
    for heading in section_order:
        if heading == GENERATED_SUMMARY_SECTION_KEY:
            # 요약 belongs to generated_summary; do not duplicate as a section
            continue
        sec = sections.get(heading) if isinstance(sections, dict) else None
        if not isinstance(sec, dict):
            continue
        chunk_texts = _section_chunk_texts(sec)
        section_text = sec.get("text") if isinstance(sec.get("text"), str) else ""
        if not section_text and not chunk_texts:
            warnings.append(
                f"line {line_number}: section {heading!r} is empty; dropped"
            )
            continue
        section_url = _first_url(sec)
        norm_heading, h_warns = _normalize_section_heading(
            heading, work_title=work_title, section_url=section_url
        )
        warnings.extend(f"line {line_number}: {w}" for w in h_warns)
        norm_path_key = normalize_section_path([norm_heading])
        occurrence = root_path_seen[norm_path_key]
        root_path_seen[norm_path_key] += 1
        section_obj = _make_section(
            page_id=root_page_id,
            heading_path=[norm_heading],
            order=section_index,
            text=section_text or "",
            links=_section_links(sec),
            depth=1,
            occurrence=occurrence,
            page_relation=root_relation,
        )
        root_page.sections.append(section_obj)
        new_chunks, chunk_index = _make_chunks_for_section(
            page=root_page,
            section=section_obj,
            chunk_texts=chunk_texts,
            base_chunk_index=chunk_index,
            fallback_url=canonical_url,
        )
        chunks.extend(new_chunks)
        section_index += 1

    root_page.document_quality = _compute_document_quality(root_page)
    pages.append(root_page)

    # ---- subpages -> separate pages ----
    subpages = record.get("subpages") or {}
    if isinstance(subpages, dict):
        for parent_key, items in subpages.items():
            if not isinstance(items, list):
                continue
            relation = relation_from_subpage_key(parent_key)
            page_type = page_type_from_relation(relation)
            for sp in items:
                if not isinstance(sp, dict):
                    continue
                sp_url = sp.get("url") if isinstance(sp.get("url"), str) else None
                sp_title, t_warns = _resolve_subpage_title(
                    raw_title=sp.get("title") if isinstance(sp.get("title"), str) else None,
                    url=sp_url,
                    work_title=work_title,
                    relation=relation,
                )
                warnings.extend(f"line {line_number}: {w}" for w in t_warns)

                sp_page_id = sha1_id(
                    sp_url or "", work_title, sp_title, relation, parent_key
                )
                sp_page = PageV4(
                    schema_version=SCHEMA_VERSION_PAGE,
                    page_id=sp_page_id,
                    work_id=work_id,
                    work_title=work_title,
                    page_title=sp_title,
                    page_type=page_type,
                    relation=relation,
                    canonical_url=sp_url,
                    parent_url=canonical_url,
                    aliases=[],
                    categories=[parent_key] if isinstance(parent_key, str) else [],
                    source=PageSource(
                        site="namu.wiki",
                        fetched_at=fetched_at,
                        revision_time=None,
                    ),
                    crawl=PageCrawl(
                        seed_title=seed_title if isinstance(seed_title, str) else None,
                        depth=max(depth, 0) + 1,
                        discovery_reason="subpage",
                        parent_page_id=root_page_id,
                    ),
                    sections=[],
                    generated_summary=GeneratedSummary(
                        model=None,
                        text=sp.get("summary") if isinstance(sp.get("summary"), str) else None,
                        bullets=[],
                        created_at=None,
                    ),
                )

                # Subpage body: prefer chunks > sections > raw_text
                sp_chunks_raw = sp.get("chunks")
                sp_sections_raw = sp.get("sections")
                sp_raw_text = sp.get("raw_text") if isinstance(sp.get("raw_text"), str) else ""

                sp_chunk_index = 0
                sp_section_index = 0
                sp_path_seen: Counter = Counter()

                if isinstance(sp_sections_raw, dict) and sp_sections_raw:
                    for inner_heading, inner_sec in sp_sections_raw.items():
                        if not isinstance(inner_sec, dict):
                            continue
                        inner_chunk_texts = _section_chunk_texts(inner_sec)
                        inner_text = (
                            inner_sec.get("text")
                            if isinstance(inner_sec.get("text"), str)
                            else ""
                        )
                        if not inner_text and not inner_chunk_texts:
                            continue
                        inner_heading_str = inner_heading or DEFAULT_BODY_HEADING
                        inner_path_key = normalize_section_path([inner_heading_str])
                        inner_occurrence = sp_path_seen[inner_path_key]
                        sp_path_seen[inner_path_key] += 1
                        section_obj = _make_section(
                            page_id=sp_page_id,
                            heading_path=[inner_heading_str],
                            order=sp_section_index,
                            text=inner_text or "",
                            links=_section_links(inner_sec),
                            occurrence=inner_occurrence,
                            page_relation=relation,
                        )
                        sp_page.sections.append(section_obj)
                        new_chunks, sp_chunk_index = _make_chunks_for_section(
                            page=sp_page,
                            section=section_obj,
                            chunk_texts=inner_chunk_texts,
                            base_chunk_index=sp_chunk_index,
                            fallback_url=sp_url,
                        )
                        chunks.extend(new_chunks)
                        sp_section_index += 1
                else:
                    chunk_texts: List[str]
                    if isinstance(sp_chunks_raw, list) and sp_chunks_raw:
                        chunk_texts = [
                            c.strip()
                            for c in sp_chunks_raw
                            if isinstance(c, str) and c.strip()
                        ]
                    else:
                        chunk_texts = _split_paragraphs(sp_raw_text)
                    if chunk_texts or sp_raw_text.strip():
                        section_obj = _make_section(
                            page_id=sp_page_id,
                            heading_path=[DEFAULT_BODY_HEADING],
                            order=0,
                            text=sp_raw_text.strip(),
                            links=[sp_url] if sp_url else [],
                            occurrence=0,
                            page_relation=relation,
                        )
                        sp_page.sections.append(section_obj)
                        new_chunks, sp_chunk_index = _make_chunks_for_section(
                            page=sp_page,
                            section=section_obj,
                            chunk_texts=chunk_texts or [sp_raw_text.strip()],
                            base_chunk_index=0,
                            fallback_url=sp_url,
                        )
                        chunks.extend(new_chunks)

                sp_page.document_quality = _compute_document_quality(sp_page)
                pages.append(sp_page)

    return pages, chunks, warnings


def convert_jsonl(
    input_path: Path,
    *,
    limit: Optional[int] = None,
) -> Tuple[List[PageV4], List[ChunkV4], List[str], int]:
    """Convert a v3 JSONL file. Returns (pages, chunks, warnings, input_record_count)."""
    pages: List[PageV4] = []
    chunks: List[ChunkV4] = []
    warnings: List[str] = []
    n = 0
    for line_no, record in _iter_jsonl(input_path):
        if limit is not None and n >= limit:
            break
        n += 1
        try:
            p, c, w = convert_record(record, line_number=line_no)
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"line {line_no}: convert failed: {exc!r}")
            continue
        pages.extend(p)
        chunks.extend(c)
        warnings.extend(w)
    return pages, chunks, warnings, n


def write_jsonl(items: Iterable[Any], path: Path) -> int:
    """Write ``items`` (each having ``.to_dict()`` or being dict-like) as JSONL."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            if hasattr(item, "to_dict"):
                obj = item.to_dict()
            else:
                obj = item
            f.write(json.dumps(obj, ensure_ascii=False))
            f.write("\n")
            count += 1
    return count
