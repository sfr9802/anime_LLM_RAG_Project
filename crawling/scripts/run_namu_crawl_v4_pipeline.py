"""CLI: production-side v4 pipeline wrapper (Phase 5.1).

End-to-end orchestrator that takes a ``namu_anime_v3.jsonl`` produced by
``crawl_namu.py`` and runs every Phase 1–5 stage in order, ending with
the audit gate. The result is a single output directory that holds
*everything* a downstream consumer needs to inspect a re-crawl::

    pages_v4.jsonl
    chunks_v4.jsonl
    rag_chunks.jsonl
    split_manifest.json
    split_manifest.report.json
    sft/sft_query_rewrite.{train,valid,test}.jsonl
    sft/sft_context_answer.{train,valid,test}.jsonl
    sft/sft_export_report.json
    audit/crawl_v4_audit_report.json
    audit/crawl_v4_audit_report.md
    crawl_run_manifest.json

Why this script exists:

* ``crawl_namu.py`` is the heavy production crawler (Selenium + MySQL +
  MongoDB). Running it from inside this wrapper would require all of
  those services to be up. Instead this wrapper takes the v3 JSONL it
  produces (``--v3-input``) as the contract boundary — that file is the
  canonical handoff between "crawling" and "v4 pipeline".
* ``light_crawl_namu.py`` is *not* an acceptable substitute: it
  collapses every page into a single ``본문`` section, which the audit
  harness will rightly flag (mean section count < 1.5, summary skew
  100%). Use ``crawl_namu.py`` for production re-crawls.

Usage::

    # full pipeline on a real v3 file
    python -m scripts.run_namu_crawl_v4_pipeline \\
        --v3-input data/namu_anime_v3.jsonl \\
        --out-dir eval/reports/namu-v4-rerun \\
        --crawler-name crawl_namu \\
        --target-range 2024-01:2025-12 \\
        --fail-on-warning

    # dry-run with a small slice
    python -m scripts.run_namu_crawl_v4_pipeline \\
        --v3-input data/namu_anime_v3.jsonl \\
        --out-dir eval/reports/namu-v4-dryrun \\
        --limit 50 \\
        --crawler-name crawl_namu \\
        --target-range "dryrun-50pages"

The wrapper is intentionally a thin shell over the existing per-stage
CLIs (``scripts.convert_namu_v3_to_v4`` / ``export_rag_chunks`` /
``build_split_manifest`` / ``build_sft_datasets`` / ``audit_crawl_v4``);
it does *not* re-implement any of them so a downstream change to those
CLIs flows through automatically.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from eval.harness.crawl_run_manifest import (
    CrawlRunManifest,
    write_crawl_run_manifest,
)
from scripts import audit_crawl_v4 as audit_cli
from scripts import build_sft_datasets as sft_cli
from scripts import build_split_manifest as manifest_cli
from scripts import convert_namu_v3_to_v4 as convert_cli
from scripts import export_rag_chunks as export_cli


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_commit_sha() -> Optional[str]:
    """Best-effort git HEAD SHA, or ``None`` when git is unavailable."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return out.decode("utf-8", errors="replace").strip() or None
    except Exception:
        return None


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            if raw.strip():
                n += 1
    return n


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Run the v4 pipeline (convert -> export rag chunks -> split "
            "manifest -> sft datasets -> audit) on a v3 JSONL produced by "
            "crawl_namu.py and emit a crawl_run_manifest.json."
        )
    )
    p.add_argument(
        "--v3-input",
        required=True,
        help=(
            "path to namu_anime_v3.jsonl produced by crawl_namu.py. "
            "(light_crawl_namu output is rejected by --reject-light unless "
            "you opt in.)"
        ),
    )
    p.add_argument(
        "--out-dir",
        required=True,
        help="output directory; created if missing",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap on input v3 records (use for dry-runs)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=42,
        help="RNG seed for the split manifest (default: %(default)s)",
    )
    p.add_argument(
        "--train-ratio",
        type=float,
        default=0.8,
        help="train ratio (default: %(default)s)",
    )
    p.add_argument(
        "--valid-ratio",
        type=float,
        default=0.1,
        help="valid ratio (default: %(default)s)",
    )
    p.add_argument(
        "--test-ratio",
        type=float,
        default=0.1,
        help="test ratio (default: %(default)s)",
    )
    p.add_argument(
        "--embedding-text-variant",
        default="title_section",
        help=(
            "rag_chunks embedding_text variant; one of "
            "raw / title / title_section / title_section_alias"
        ),
    )
    p.add_argument(
        "--max-records-per-split",
        type=int,
        default=None,
        help="cap SFT records per (kind, split); default: no cap",
    )
    p.add_argument(
        "--allow-missing-docs",
        action="store_true",
        help="forwarded to scripts.build_sft_datasets",
    )
    p.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="exit non-zero if the audit emits any warnings",
    )
    p.add_argument(
        "--skip-sft",
        action="store_true",
        help="skip SFT dataset export (audit still runs without --sft-report)",
    )

    # Provenance fields written into crawl_run_manifest.json
    p.add_argument(
        "--crawler-name",
        default="crawl_namu",
        help="crawler that produced --v3-input (default: %(default)s)",
    )
    p.add_argument(
        "--crawler-version", default=None, help="crawler version string"
    )
    p.add_argument(
        "--source",
        default="namu.wiki",
        help="data source name (default: %(default)s)",
    )
    p.add_argument(
        "--target-range",
        default=None,
        help="seed/period range, e.g. '2024-01:2025-12'",
    )
    p.add_argument(
        "--target-period",
        default=None,
        help="human-readable target period (free-form)",
    )
    p.add_argument(
        "--seed-count",
        type=int,
        default=0,
        help="number of seeds the crawler started from (provenance only)",
    )
    p.add_argument(
        "--total-pages-attempted",
        type=int,
        default=0,
        help="number of pages attempted by the crawler (provenance only)",
    )
    p.add_argument(
        "--total-pages-failed",
        type=int,
        default=0,
        help="number of pages that the crawler failed to fetch (provenance only)",
    )
    p.add_argument(
        "--retry-count",
        type=int,
        default=0,
        help="cumulative retry count from the crawler (provenance only)",
    )
    p.add_argument(
        "--failed-urls-file",
        default=None,
        help="optional JSON file containing a list[str] of failed URLs",
    )
    p.add_argument(
        "--notes",
        default="",
        help="free-form note string written to the manifest",
    )
    return p.parse_args(argv)


def _load_failed_urls(path_str: Optional[str]) -> List[str]:
    if not path_str:
        return []
    p = Path(path_str)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        obj = json.load(f)
    if not isinstance(obj, list):
        raise ValueError(
            f"--failed-urls-file must contain a JSON list; got {type(obj).__name__}"
        )
    return [str(u) for u in obj if isinstance(u, str)]


def main(argv=None) -> int:
    args = parse_args(argv)

    v3_input = Path(args.v3_input)
    if not v3_input.exists():
        print(f"v3 input not found: {v3_input}", file=sys.stderr)
        return 2
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    started_at = _utcnow_iso()
    started_perf = time.perf_counter()
    failed_urls = _load_failed_urls(args.failed_urls_file)

    pages_path = out_dir / "pages_v4.jsonl"
    chunks_v4_path = out_dir / "chunks_v4.jsonl"
    rag_chunks_path = out_dir / "rag_chunks.jsonl"
    manifest_path = out_dir / "split_manifest.json"
    manifest_report_path = out_dir / "split_manifest.report.json"
    sft_dir = out_dir / "sft"
    sft_report_path = sft_dir / "sft_export_report.json"
    audit_dir = out_dir / "audit"
    audit_json_path = audit_dir / "crawl_v4_audit_report.json"
    audit_md_path = audit_dir / "crawl_v4_audit_report.md"
    crawl_run_manifest_path = out_dir / "crawl_run_manifest.json"

    # ------------------------------------------------- Stage 1: v3 -> v4
    print(f"[1/5] convert v3 -> v4 ({v3_input} -> {out_dir})")
    convert_argv = [
        "--input", str(v3_input),
        "--out-dir", str(out_dir),
    ]
    if args.limit is not None:
        convert_argv += ["--limit", str(args.limit)]
    rc = convert_cli.main(convert_argv)
    if rc != 0:
        print("convert_namu_v3_to_v4 failed; aborting pipeline", file=sys.stderr)
        return rc

    # ------------------------------------------------- Stage 2: rag chunks
    print(f"[2/5] export rag chunks -> {rag_chunks_path}")
    export_argv = [
        "--input", str(pages_path),
        "--out", str(rag_chunks_path),
        "--embedding-text-variant", args.embedding_text_variant,
    ]
    rc = export_cli.main(export_argv)
    if rc != 0:
        print("export_rag_chunks failed; aborting pipeline", file=sys.stderr)
        return rc

    # ------------------------------------------------- Stage 3: split manifest
    print(f"[3/5] build split manifest -> {manifest_path}")
    manifest_argv = [
        "--input", str(pages_path),
        "--out", str(manifest_path),
        "--seed", str(args.seed),
        "--train-ratio", str(args.train_ratio),
        "--valid-ratio", str(args.valid_ratio),
        "--test-ratio", str(args.test_ratio),
        "--chunks", str(rag_chunks_path),
    ]
    rc = manifest_cli.main(manifest_argv)
    if rc != 0:
        print("build_split_manifest failed; aborting pipeline", file=sys.stderr)
        return rc

    # ------------------------------------------------- Stage 4: sft datasets
    if args.skip_sft:
        print("[4/5] skipping SFT export (--skip-sft)")
        sft_emitted = False
    else:
        print(f"[4/5] build sft datasets -> {sft_dir}")
        sft_argv = [
            "--pages", str(pages_path),
            "--chunks", str(rag_chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(sft_dir),
        ]
        if args.max_records_per_split is not None:
            sft_argv += ["--max-records-per-split", str(args.max_records_per_split)]
        if args.allow_missing_docs:
            sft_argv += ["--allow-missing-docs"]
        rc = sft_cli.main(sft_argv)
        if rc != 0:
            print("build_sft_datasets failed; aborting pipeline", file=sys.stderr)
            return rc
        sft_emitted = sft_report_path.exists()

    # ------------------------------------------------- Stage 5: audit
    print(f"[5/5] audit crawl -> {audit_dir}")
    audit_argv = [
        "--pages", str(pages_path),
        "--chunks", str(rag_chunks_path),
        "--manifest", str(manifest_path),
        "--out-dir", str(audit_dir),
    ]
    if sft_emitted:
        audit_argv += ["--sft-report", str(sft_report_path)]
    if args.fail_on_warning:
        audit_argv += ["--fail-on-warning"]
    audit_rc = audit_cli.main(audit_argv)

    # ------------------------------------------------- crawl_run_manifest
    finished_at = _utcnow_iso()
    pages_count = _count_jsonl(pages_path)
    output_files = {
        "v3_input": str(v3_input),
        "pages_v4": str(pages_path),
        "chunks_v4": str(chunks_v4_path),
        "rag_chunks": str(rag_chunks_path),
        "split_manifest": str(manifest_path),
        "split_manifest_report": str(manifest_report_path),
        "audit_json": str(audit_json_path),
        "audit_markdown": str(audit_md_path),
    }
    if sft_emitted:
        output_files["sft_export_report"] = str(sft_report_path)
        output_files["sft_dir"] = str(sft_dir)

    manifest = CrawlRunManifest(
        crawl_started_at=started_at,
        crawl_finished_at=finished_at,
        source=args.source,
        target_range=args.target_range,
        target_period=args.target_period,
        seed_count=int(args.seed_count or 0),
        total_pages_attempted=int(args.total_pages_attempted or 0)
        or pages_count,
        total_pages_success=pages_count,
        total_pages_failed=int(args.total_pages_failed or 0),
        failed_urls=failed_urls,
        retry_count=int(args.retry_count or 0),
        crawler_name=args.crawler_name,
        crawler_version=args.crawler_version,
        git_commit=_git_commit_sha(),
        output_files=output_files,
        notes=args.notes,
    )
    write_crawl_run_manifest(manifest, crawl_run_manifest_path)
    elapsed = time.perf_counter() - started_perf
    print(
        f"wrote: {crawl_run_manifest_path} "
        f"(pages={pages_count}, elapsed={elapsed:.1f}s)"
    )

    return audit_rc


if __name__ == "__main__":
    sys.exit(main())
