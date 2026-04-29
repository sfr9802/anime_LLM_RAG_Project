"""Tests for the Phase 5.1 crawl_run_manifest module.

Covers serialisation round-trip, required-field validation, and the
disk read/write helpers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.harness.crawl_run_manifest import (
    CrawlRunManifest,
    SCHEMA_VERSION_CRAWL_RUN_MANIFEST,
    manifest_from_dict,
    read_crawl_run_manifest,
    write_crawl_run_manifest,
)


def _minimal_manifest() -> CrawlRunManifest:
    return CrawlRunManifest(
        source="namu.wiki",
        crawler_name="crawl_namu",
        crawler_version="2026.04",
        target_range="2024-01:2025-12",
        seed_count=42,
        total_pages_attempted=100,
        total_pages_success=95,
        total_pages_failed=5,
        failed_urls=["https://namu.wiki/w/foo", "https://namu.wiki/w/bar"],
        retry_count=7,
        output_files={"pages_v4": "data/pages_v4.jsonl"},
        notes="dry-run",
    )


def test_to_dict_includes_schema_version():
    m = _minimal_manifest()
    d = m.to_dict()
    assert d["schema_version"] == SCHEMA_VERSION_CRAWL_RUN_MANIFEST
    assert d["crawler_name"] == "crawl_namu"
    assert d["seed_count"] == 42
    assert d["failed_urls"] == [
        "https://namu.wiki/w/foo",
        "https://namu.wiki/w/bar",
    ]


def test_round_trip_through_dict():
    m = _minimal_manifest()
    obj = m.to_dict()
    rt = manifest_from_dict(obj)
    assert rt.crawler_name == m.crawler_name
    assert rt.failed_urls == m.failed_urls
    assert rt.target_range == m.target_range
    assert rt.notes == m.notes
    assert rt.output_files == m.output_files


def test_round_trip_through_disk(tmp_path: Path):
    m = _minimal_manifest()
    p = tmp_path / "crawl_run_manifest.json"
    write_crawl_run_manifest(m, p)
    assert p.exists()
    # JSON file should be valid JSON, sort_keys=True
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION_CRAWL_RUN_MANIFEST
    keys = list(raw.keys())
    assert keys == sorted(keys), "write_crawl_run_manifest should sort keys"
    rt = read_crawl_run_manifest(p)
    assert rt.crawler_name == m.crawler_name
    assert rt.seed_count == m.seed_count


def test_missing_required_field_raises():
    bad = {
        "schema_version": SCHEMA_VERSION_CRAWL_RUN_MANIFEST,
        "source": "namu.wiki",
        # crawler_name missing
    }
    with pytest.raises(ValueError) as exc:
        manifest_from_dict(bad)
    assert "crawler_name" in str(exc.value)


def test_wrong_schema_version_raises():
    bad = {
        "schema_version": "wrong_version",
        "source": "namu.wiki",
        "crawler_name": "crawl_namu",
    }
    with pytest.raises(ValueError) as exc:
        manifest_from_dict(bad)
    assert "schema_version" in str(exc.value)


def test_bad_failed_urls_type_raises():
    bad = {
        "schema_version": SCHEMA_VERSION_CRAWL_RUN_MANIFEST,
        "source": "namu.wiki",
        "crawler_name": "crawl_namu",
        "failed_urls": [1, 2, 3],  # ints, not strings
    }
    with pytest.raises(ValueError) as exc:
        manifest_from_dict(bad)
    assert "failed_urls" in str(exc.value)


def test_bad_output_files_type_raises():
    bad = {
        "schema_version": SCHEMA_VERSION_CRAWL_RUN_MANIFEST,
        "source": "namu.wiki",
        "crawler_name": "crawl_namu",
        "output_files": [{"pages": "x"}],  # list, not dict
    }
    with pytest.raises(ValueError) as exc:
        manifest_from_dict(bad)
    assert "output_files" in str(exc.value)


def test_unknown_fields_are_ignored():
    """Forward-compat: a slightly newer producer may add fields we
    don't know about. The loader should ignore them rather than crash."""
    obj = {
        "schema_version": SCHEMA_VERSION_CRAWL_RUN_MANIFEST,
        "source": "namu.wiki",
        "crawler_name": "crawl_namu",
        "extra_field_we_dont_know_about": {"nested": True},
    }
    m = manifest_from_dict(obj)
    assert m.source == "namu.wiki"
    assert m.crawler_name == "crawl_namu"


def test_defaults_yield_a_valid_manifest():
    """A bare-bones manifest with just the required identity fields
    serialises and round-trips cleanly. This is the minimum that the
    pipeline wrapper writes when only --crawler-name is set."""
    m = CrawlRunManifest(source="namu.wiki", crawler_name="crawl_namu")
    obj = m.to_dict()
    rt = manifest_from_dict(obj)
    assert rt.source == "namu.wiki"
    assert rt.crawler_name == "crawl_namu"
    assert rt.failed_urls == []
    assert rt.output_files == {}
    assert rt.crawl_started_at is None


def test_int_coercion_for_count_fields():
    """Counts arriving as numeric strings (e.g., from a spreadsheet
    export) are coerced to ints so the manifest stays consistent."""
    obj = {
        "schema_version": SCHEMA_VERSION_CRAWL_RUN_MANIFEST,
        "source": "namu.wiki",
        "crawler_name": "crawl_namu",
        "seed_count": "10",
        "total_pages_attempted": "200",
        "retry_count": None,
    }
    m = manifest_from_dict(obj)
    assert m.seed_count == 10
    assert m.total_pages_attempted == 200
    assert m.retry_count == 0
