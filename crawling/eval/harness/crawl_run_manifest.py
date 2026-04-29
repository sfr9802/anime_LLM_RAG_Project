"""Phase 5.1 — crawl-run provenance manifest.

A ``crawl_run_manifest.json`` records *how* a v4 dataset was produced:
which crawler, which seeds, which time window, how many pages were tried
vs. succeeded, and which output files the pipeline wrote. The manifest
is written by the pipeline wrapper (``scripts.run_namu_crawl_v4_pipeline``)
or directly by anything that calls ``crawl_namu.py`` and wants to keep
provenance.

The manifest is **append-only metadata**, not an authority — chunk /
page / split files are still the source of truth for content. This file
exists so that months from now we can answer:

* Which crawler version produced this dataset?
* When did the crawl start and finish?
* How many pages were attempted, succeeded, failed?
* What was the target seed range / period?
* Which files belong together (pages, chunks, manifest, audit, ...)?

Schema is intentionally permissive: every field has a sensible default
so callers can populate the bits they know and leave the rest empty.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION_CRAWL_RUN_MANIFEST = "namu_crawl_run_manifest_v1"


# Required fields for `manifest_from_dict` — anything missing here is
# treated as a programmer error. The rest can be empty/None.
_REQUIRED_FIELDS: tuple = ("schema_version", "source", "crawler_name")


@dataclass
class CrawlRunManifest:
    """Provenance manifest for one crawl run.

    Fields are deliberately flat (no nested dataclasses) so the JSON
    output is easy to read in a CI log without traversing deep keys.
    """

    schema_version: str = SCHEMA_VERSION_CRAWL_RUN_MANIFEST

    # When did the crawl run? ISO-8601 strings; left empty if unknown.
    crawl_started_at: Optional[str] = None
    crawl_finished_at: Optional[str] = None

    # What was crawled?
    source: str = ""  # e.g. "namu.wiki"
    target_range: Optional[str] = None  # e.g. "2024-01:2025-12"
    target_period: Optional[str] = None  # alias / human-readable variant

    # Seed-level + page-level counters.
    seed_count: int = 0
    total_pages_attempted: int = 0
    total_pages_success: int = 0
    total_pages_failed: int = 0
    failed_urls: List[str] = field(default_factory=list)
    retry_count: int = 0

    # Crawler identity.
    crawler_name: str = ""
    crawler_version: Optional[str] = None
    git_commit: Optional[str] = None

    # Output file inventory: logical name -> absolute / relative path.
    output_files: Dict[str, str] = field(default_factory=dict)

    # Free-form notes — useful for "this run was a smoke / dry-run / full
    # quarter". Single string by design; multiline is fine.
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def manifest_from_dict(obj: Any) -> CrawlRunManifest:
    """Validate ``obj`` (a JSON-decoded dict) and build a CrawlRunManifest.

    Raises :class:`ValueError` when required fields are missing or when a
    field has the wrong type. Unknown fields are ignored so the loader
    can read manifests written by a slightly newer producer.
    """
    if not isinstance(obj, dict):
        raise ValueError(
            f"crawl_run_manifest must decode to a dict, got {type(obj).__name__}"
        )

    missing = [f for f in _REQUIRED_FIELDS if f not in obj]
    if missing:
        raise ValueError(
            f"crawl_run_manifest is missing required field(s): {missing}"
        )

    schema_version = obj.get("schema_version")
    if schema_version != SCHEMA_VERSION_CRAWL_RUN_MANIFEST:
        # Surface as a warning-ish ValueError; we do not auto-migrate.
        raise ValueError(
            f"crawl_run_manifest schema_version {schema_version!r} does not "
            f"match expected {SCHEMA_VERSION_CRAWL_RUN_MANIFEST!r}"
        )

    failed_urls = obj.get("failed_urls", []) or []
    if not isinstance(failed_urls, list) or not all(
        isinstance(u, str) for u in failed_urls
    ):
        raise ValueError("failed_urls must be a list[str] when provided")

    output_files = obj.get("output_files", {}) or {}
    if not isinstance(output_files, dict):
        raise ValueError("output_files must be a dict when provided")
    for k, v in output_files.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError("output_files keys and values must both be strings")

    return CrawlRunManifest(
        schema_version=schema_version,
        crawl_started_at=obj.get("crawl_started_at"),
        crawl_finished_at=obj.get("crawl_finished_at"),
        source=obj.get("source") or "",
        target_range=obj.get("target_range"),
        target_period=obj.get("target_period"),
        seed_count=int(obj.get("seed_count") or 0),
        total_pages_attempted=int(obj.get("total_pages_attempted") or 0),
        total_pages_success=int(obj.get("total_pages_success") or 0),
        total_pages_failed=int(obj.get("total_pages_failed") or 0),
        failed_urls=list(failed_urls),
        retry_count=int(obj.get("retry_count") or 0),
        crawler_name=obj.get("crawler_name") or "",
        crawler_version=obj.get("crawler_version"),
        git_commit=obj.get("git_commit"),
        output_files=dict(output_files),
        notes=obj.get("notes") or "",
    )


def write_crawl_run_manifest(manifest: CrawlRunManifest, path: Path) -> None:
    """Serialise ``manifest`` as pretty-printed JSON at ``path``.

    Creates parent directories if needed. Uses ``sort_keys=True`` so two
    runs that produce equivalent manifests are byte-identical.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            manifest.to_dict(),
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


def read_crawl_run_manifest(path: Path) -> CrawlRunManifest:
    """Load a manifest from disk via :func:`manifest_from_dict`."""
    with path.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    return manifest_from_dict(obj)
