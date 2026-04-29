"""Smoke tests for scripts.run_namu_crawl_v4_pipeline.

The wrapper chains stages we already test individually; this file just
verifies the orchestration behaviour: required inputs, output files,
and the crawl_run_manifest produced at the end.
"""

from __future__ import annotations

import json
from pathlib import Path

from eval.harness.crawl_run_manifest import (
    SCHEMA_VERSION_CRAWL_RUN_MANIFEST,
    read_crawl_run_manifest,
)
from scripts.run_namu_crawl_v4_pipeline import main as pipeline_main


def _write_v3_record(seed: str, sections: dict) -> dict:
    return {
        "seed": seed,
        "title": seed,
        "url": f"https://namu.wiki/w/{seed}",
        "canonical_url": f"https://namu.wiki/w/{seed}",
        "aliases": [],
        "sections": sections,
        "section_order": list(sections.keys()),
        "meta": {
            "seed_title": seed,
            "depth": 0,
            "fetched_at": "2026-04-01T00:00:00Z",
        },
        "subpages": [],
        "summary": "",
        "sum_bullets": [],
    }


def _make_v3_jsonl(path: Path, n: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = (
        "이 작품은 2024년에 방영된 애니메이션이다. 충분히 긴 본문 텍스트이며, "
        "여러 문장이 포함되어 있다. 두 번째 문장. 세 번째 문장."
    )
    with path.open("w", encoding="utf-8") as f:
        for i in range(n):
            seed = f"작품_{i}"
            rec = _write_v3_record(
                seed,
                sections={
                    "줄거리": {
                        "text": body,
                        "chunks": [body],
                        "urls": [f"https://namu.wiki/w/{seed}"],
                        "model": None,
                        "ts": None,
                    },
                    "등장인물": {
                        "text": body,
                        "chunks": [body],
                        "urls": [f"https://namu.wiki/w/{seed}/등장인물"],
                        "model": None,
                        "ts": None,
                    },
                    "설정": {
                        "text": body,
                        "chunks": [body],
                        "urls": [f"https://namu.wiki/w/{seed}/설정"],
                        "model": None,
                        "ts": None,
                    },
                },
            )
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def test_pipeline_writes_full_output_set(tmp_path: Path):
    v3 = tmp_path / "namu_anime_v3.jsonl"
    _make_v3_jsonl(v3, n=3)
    out_dir = tmp_path / "out"

    rc = pipeline_main(
        [
            "--v3-input", str(v3),
            "--out-dir", str(out_dir),
            "--crawler-name", "crawl_namu",
            "--target-range", "test-range",
            "--seed-count", "3",
            "--total-pages-attempted", "3",
            "--retry-count", "0",
            "--notes", "unit-test smoke",
            # Use a tiny manifest to keep the SFT export quick
            "--max-records-per-split", "5",
        ]
    )
    # The pipeline returns the audit's exit code. Without --fail-on-warning,
    # it should be 0 even if the small fixture surfaces some warnings.
    assert rc == 0

    expected = [
        out_dir / "pages_v4.jsonl",
        out_dir / "chunks_v4.jsonl",
        out_dir / "rag_chunks.jsonl",
        out_dir / "split_manifest.json",
        out_dir / "split_manifest.report.json",
        out_dir / "audit" / "crawl_v4_audit_report.json",
        out_dir / "audit" / "crawl_v4_audit_report.md",
        out_dir / "sft" / "sft_export_report.json",
        out_dir / "crawl_run_manifest.json",
    ]
    for p in expected:
        assert p.exists(), f"missing pipeline output: {p}"

    manifest = read_crawl_run_manifest(out_dir / "crawl_run_manifest.json")
    assert manifest.schema_version == SCHEMA_VERSION_CRAWL_RUN_MANIFEST
    assert manifest.crawler_name == "crawl_namu"
    assert manifest.target_range == "test-range"
    assert manifest.seed_count == 3
    assert manifest.notes == "unit-test smoke"
    assert manifest.crawl_started_at is not None
    assert manifest.crawl_finished_at is not None
    assert "pages_v4" in manifest.output_files
    assert "audit_json" in manifest.output_files
    assert "sft_export_report" in manifest.output_files


def test_pipeline_skip_sft_omits_sft_block(tmp_path: Path):
    v3 = tmp_path / "namu_anime_v3.jsonl"
    _make_v3_jsonl(v3, n=2)
    out_dir = tmp_path / "out"

    rc = pipeline_main(
        [
            "--v3-input", str(v3),
            "--out-dir", str(out_dir),
            "--crawler-name", "crawl_namu",
            "--skip-sft",
        ]
    )
    assert rc == 0
    assert not (out_dir / "sft" / "sft_export_report.json").exists()
    manifest = read_crawl_run_manifest(out_dir / "crawl_run_manifest.json")
    assert "sft_export_report" not in manifest.output_files


def test_pipeline_rejects_missing_v3_input(tmp_path: Path):
    rc = pipeline_main(
        [
            "--v3-input", str(tmp_path / "no_such_file.jsonl"),
            "--out-dir", str(tmp_path / "out"),
            "--crawler-name", "crawl_namu",
        ]
    )
    assert rc != 0
