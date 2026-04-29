"""v4 Page / Chunk schema for the namu_anime RAG dataset.

The v3 dataset conflates ``title`` with section names like ``등장인물`` /
``설정`` and hides character/setting data inside ``subpages``. v4 separates
the work, the page, and the page's role:

  - ``work_title``  : canonical work name (the seed)
  - ``page_title``  : the actual page name (work / character page / setting page ...)
  - ``page_type``   : the kind of document (``work``, ``character``, ...)
  - ``relation``    : how this page relates to the root work

Chunks are denormalized so each one carries enough metadata to be used as a
retrieval unit on its own (incl. ``text_for_embedding``).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Iterable, List, Literal, Optional
from urllib.parse import unquote

SCHEMA_VERSION_PAGE = "namu_anime_v4_page"
SCHEMA_VERSION_CHUNK = "namu_anime_v4_chunk"

PageType = Literal[
    "work",
    "character",
    "setting",
    "plot",
    "review",
    "production",
    "episode",
    "other",
]

Relation = Literal[
    "main",
    "character",
    "setting",
    "plot",
    "review",
    "production",
    "episode",
    "other",
]

DiscoveryReason = Literal[
    "root",
    "subpage",
    "character_link",
    "setting_link",
    "other",
]

PAGE_TYPES: tuple = (
    "work",
    "character",
    "setting",
    "plot",
    "review",
    "production",
    "episode",
    "other",
)

RELATIONS: tuple = (
    "main",
    "character",
    "setting",
    "plot",
    "review",
    "production",
    "episode",
    "other",
)


GENERIC_TITLES: frozenset = frozenset(
    [
        "등장인물",
        "캐릭터",
        "설정",
        "세계관",
        "설정/세계관",
        "줄거리",
        "스토리",
        "평가",
        "개요",
        "방영 목록",
        "방영목록",
        "에피소드",
        "기타",
        "관련 문서",
        "관련문서",
        "외부 링크",
        "외부링크",
        "본문",
        "요약",
    ]
)


_SUBPAGE_RELATION_MAP = {
    "등장인물": "character",
    "캐릭터": "character",
    "character": "character",
    "characters": "character",
    "설정": "setting",
    "세계관": "setting",
    "설정/세계관": "setting",
    "용어": "setting",
    "줄거리": "plot",
    "스토리": "plot",
    "story": "plot",
    "평가": "review",
    "review": "review",
    "방영 목록": "episode",
    "방영목록": "episode",
    "에피소드": "episode",
    "episode": "episode",
    "episodes": "episode",
    "제작": "production",
    "production": "production",
}


def normalize_text_for_id(value: str) -> str:
    """NFKC + lowercase + collapse whitespace; for ID hashing only."""
    if not value:
        return ""
    s = unicodedata.normalize("NFKC", value).strip().lower()
    return re.sub(r"\s+", " ", s)


def is_generic_title(value: Optional[str]) -> bool:
    """Return True if ``value`` is a generic section name rather than a real page name."""
    if not value:
        return True
    return normalize_text_for_id(value) in {
        normalize_text_for_id(t) for t in GENERIC_TITLES
    }


def page_type_from_relation(relation: str) -> PageType:
    if relation == "main":
        return "work"
    if relation in PAGE_TYPES:
        return relation  # type: ignore[return-value]
    return "other"


def relation_from_subpage_key(key: Optional[str]) -> Relation:
    if not key:
        return "other"
    norm = normalize_text_for_id(key)
    direct = _SUBPAGE_RELATION_MAP.get(norm)
    if direct:
        return direct  # type: ignore[return-value]
    if "등장인물" in key or "캐릭터" in key.lower() or "character" in key.lower():
        return "character"
    if any(k in key for k in ("설정", "세계관", "용어")):
        return "setting"
    if any(k in key for k in ("줄거리", "스토리")):
        return "plot"
    if "평가" in key:
        return "review"
    if "에피소드" in key or "방영" in key:
        return "episode"
    return "other"


def title_from_url(url: Optional[str]) -> Optional[str]:
    """Decode a namu.wiki URL and return the trailing path segment as a title.

    e.g. ``https://namu.wiki/w/2.5%EC%B0%A8%EC%9B%90%EC%9D%98%20%EC%9C%A0%ED%98%B9/%EB%93%B1%EC%9E%A5%EC%9D%B8%EB%AC%BC``
    -> ``2.5차원의 유혹/등장인물``.
    """
    if not url:
        return None
    try:
        decoded = unquote(url)
    except Exception:
        return None
    marker = "/w/"
    if marker in decoded:
        decoded = decoded.split(marker, 1)[1]
    return decoded.strip().strip("/") or None


def sha1_id(*parts: object, length: int = 16) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(normalize_text_for_id(str(p)).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()[:length]


def estimate_tokens(char_len: int) -> int:
    """Rough token estimate for mixed Korean/English text.

    Korean BPE tokenizers usually emit ~0.5-0.7 tokens per char. We use 0.5 as
    a conservative under-estimate suitable for length filtering.
    """
    if char_len <= 0:
        return 0
    return max(1, char_len // 2)


def join_section_path(path: Iterable[str]) -> str:
    parts = [p for p in path if p]
    return " > ".join(parts) if parts else "본문"


def normalize_section_path(path: Iterable[str]) -> str:
    """Canonical string form of a section path used for ID hashing.
    NFKC + lowercase + whitespace-collapse on each segment so that small
    formatting variations (e.g. extra space) produce the same key.
    """
    parts = [normalize_text_for_id(p) for p in path if p and p.strip()]
    if not parts:
        return normalize_text_for_id("본문")
    return ">".join(parts)


def make_section_key(
    *,
    page_id: str,
    heading_path: Iterable[str],
    occurrence: int = 0,
    length: int = 16,
) -> str:
    """Order-stable section key.

    Unlike ``section_id`` (which mixes ``order`` into the hash and therefore
    shifts when sections are reordered), ``section_key`` depends only on
    ``page_id`` + the normalized ``heading_path``. When a page has multiple
    sections that share the same path, callers pass ``occurrence`` (0, 1, 2, …
    in input order) as a deterministic disambiguator. ``occurrence=0`` (the
    common case — paths are unique) uses no disambiguator so re-ordering the
    sections does not change the key.
    """
    norm_path = normalize_section_path(heading_path)
    if occurrence <= 0:
        return sha1_id(page_id, norm_path, length=length)
    return sha1_id(page_id, norm_path, f"#{occurrence}", length=length)


# ----- Phase 1 additions: per-section / per-document quality + RAG/SFT placeholders -----

SectionType = Literal[
    "summary",
    "synopsis",
    "character",
    "setting",
    "worldview",
    "concept",
    "episode",
    "evaluation",
    "production",
    "music",
    "trivia",
    "other",
]

SECTION_TYPES: tuple = (
    "summary",
    "synopsis",
    "character",
    "setting",
    "worldview",
    "concept",
    "episode",
    "evaluation",
    "production",
    "music",
    "trivia",
    "other",
)


@dataclass
class SectionQuality:
    """Per-section quality probe filled by ``text_cleaner``.

    ``noise_score`` is 0.0..1.0 where 0.0 means clean_text == raw_text and
    1.0 means everything was stripped. Booleans are heuristic flags only.
    """

    text_length: int = 0
    noise_score: float = 0.0
    is_stub: bool = False
    has_spoiler: bool = False
    is_table_like: bool = False
    is_list_like: bool = False


@dataclass
class DocumentQuality:
    total_text_length: int = 0
    section_count: int = 0
    valid_section_count: int = 0
    is_low_quality: bool = False
    reason: Optional[str] = None


@dataclass
class Entity:
    """Lightweight entity reference. Type strings are intentionally open
    (character|organization|place|concept|work|skill|item|other) so a future
    NER module can extend without schema migration.
    """

    name: str
    type: str = "other"


@dataclass
class RelationTriple:
    """Subject/predicate/object triple. Named ``RelationTriple`` so it does
    not collide with the existing page-level ``Relation`` literal alias.
    """

    subject: str
    predicate: str
    object: str


@dataclass
class QACandidate:
    """Per-section QA candidate. ``evidence_span`` is a substring of the
    section's clean_text/raw_text that grounds the answer.
    """

    question: str
    answer: str
    evidence_span: str
    difficulty: str = "easy"  # easy|medium|hard
    answer_type: str = "fact"  # fact|summary|comparison|reasoning


@dataclass
class SectionV4:
    section_id: str
    heading_path: List[str]
    depth: int
    order: int
    text: str
    links: List[str] = field(default_factory=list)

    # --- Phase 1 additions (all optional, default-empty so existing
    #     producers / tests / consumers keep working unchanged) ---
    section_key: Optional[str] = None
    section_type: SectionType = "other"
    raw_text: str = ""
    clean_text: str = ""
    summary: Optional[str] = None
    keywords: List[str] = field(default_factory=list)
    entities: List[Entity] = field(default_factory=list)
    relations: List[RelationTriple] = field(default_factory=list)
    qa_candidates: List[QACandidate] = field(default_factory=list)
    quality: SectionQuality = field(default_factory=SectionQuality)


@dataclass
class PageSource:
    site: str = "namu.wiki"
    fetched_at: Optional[str] = None
    revision_time: Optional[str] = None


@dataclass
class PageCrawl:
    seed_title: Optional[str] = None
    depth: int = 0
    discovery_reason: DiscoveryReason = "root"
    parent_page_id: Optional[str] = None


@dataclass
class GeneratedSummary:
    model: Optional[str] = None
    text: Optional[str] = None
    bullets: List[str] = field(default_factory=list)
    created_at: Optional[str] = None


@dataclass
class PageV4:
    schema_version: str
    page_id: str
    work_id: str
    work_title: str
    page_title: str
    page_type: PageType
    relation: Relation
    canonical_url: Optional[str] = None
    parent_url: Optional[str] = None
    aliases: List[str] = field(default_factory=list)
    categories: List[str] = field(default_factory=list)
    source: PageSource = field(default_factory=PageSource)
    crawl: PageCrawl = field(default_factory=PageCrawl)
    sections: List[SectionV4] = field(default_factory=list)
    generated_summary: GeneratedSummary = field(default_factory=GeneratedSummary)

    # --- Phase 1 addition ---
    document_quality: DocumentQuality = field(default_factory=DocumentQuality)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ChunkQuality:
    is_empty: bool = False
    is_short: bool = False
    is_truncated: bool = False
    boilerplate_removed: bool = True


@dataclass
class ChunkV4:
    schema_version: str
    chunk_id: str
    page_id: str
    work_id: str
    work_title: str
    page_title: str
    page_type: PageType
    relation: Relation
    section_path: List[str]
    chunk_index: int
    text: str
    text_for_embedding: str
    char_len: int
    token_estimate: int
    retrieval_tags: List[str] = field(default_factory=list)
    source_url: Optional[str] = None
    quality: ChunkQuality = field(default_factory=ChunkQuality)

    def to_dict(self) -> dict:
        return asdict(self)


def build_text_for_embedding(
    *,
    work_title: str,
    page_title: str,
    page_type: str,
    relation: str,
    section_path: Iterable[str],
    text: str,
) -> str:
    """Compose the canonical embedding string used in v4.

    The format is fixed so retrieval tuning can rely on it across runs.
    """
    section_label = join_section_path(section_path)
    return (
        f"작품: {work_title}\n"
        f"문서: {page_title}\n"
        f"유형: {page_type}\n"
        f"관계: {relation}\n"
        f"섹션: {section_label}\n"
        f"본문: {text}"
    )
