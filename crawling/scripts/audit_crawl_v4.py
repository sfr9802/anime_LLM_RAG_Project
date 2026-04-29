"""CLI: pre-recrawl audit harness for v4 datasets (Phase 5).

Usage::

    python -m scripts.audit_crawl_v4 \\
        --pages data/pages_v4.jsonl \\
        --chunks data/rag_chunks.jsonl \\
        --manifest data/split_manifest.json \\
        --sft-report data/sft/sft_export_report.json \\
        --out-dir data/audit

Always writes a JSON report; also writes a Markdown summary unless
``--no-markdown`` is set. ``--manifest`` and ``--sft-report`` are
optional; their respective audit blocks are skipped when absent.

Threshold knobs (Phase 5 spec §3) are exposed as CLI flags so a CI
can tune them without code changes — defaults are the
:class:`AuditThresholds` defaults from ``crawl_v4_audit``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterator

from eval.harness.crawl_v4_audit import (
    AuditThresholds,
    render_markdown,
    run_full_audit,
)
from eval.harness.split_manifest import manifest_from_dict


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Audit a v4 crawl dataset (pages + chunks, optionally split "
            "manifest + sft_export_report) and emit a structured JSON + "
            "Markdown report."
        )
    )
    p.add_argument("--pages", required=True, help="path to pages_v4.jsonl")
    p.add_argument("--chunks", required=True, help="path to rag_chunks.jsonl")
    p.add_argument(
        "--manifest", default=None, help="optional path to split_manifest.json"
    )
    p.add_argument(
        "--sft-report",
        default=None,
        help="optional path to sft_export_report.json",
    )
    p.add_argument("--out-dir", required=True, help="output directory")
    p.add_argument(
        "--report-prefix",
        default="crawl_v4_audit",
        help="filename prefix for the report files (default: %(default)s)",
    )
    p.add_argument(
        "--no-markdown", action="store_true", help="skip writing the .md report"
    )
    p.add_argument(
        "--no-json", action="store_true", help="skip writing the .json report"
    )
    p.add_argument(
        "--fail-on-warning",
        action="store_true",
        help=(
            "exit with status 1 when the audit report contains one or more "
            "warnings. JSON / Markdown reports are still written before exit "
            "so a CI step can read them on failure."
        ),
    )

    # Threshold overrides
    th = AuditThresholds()
    p.add_argument("--too-short-chars", type=int, default=th.too_short_chars)
    p.add_argument("--too-long-chars", type=int, default=th.too_long_chars)
    p.add_argument("--work-skew-top-n", type=int, default=th.work_skew_top_n)
    p.add_argument("--work-skew-warn-ratio", type=float, default=th.work_skew_warn_ratio)
    p.add_argument(
        "--short-chunk-warn-ratio", type=float, default=th.short_chunk_warn_ratio
    )
    p.add_argument(
        "--unsupported-section-type-warn-ratio",
        type=float,
        default=th.unsupported_section_type_warn_ratio,
    )
    p.add_argument(
        "--aliases-missing-warn-ratio",
        type=float,
        default=th.aliases_missing_warn_ratio,
    )
    p.add_argument(
        "--fetched-at-missing-warn-ratio",
        type=float,
        default=th.fetched_at_missing_warn_ratio,
    )
    p.add_argument(
        "--work-title-missing-warn-ratio",
        type=float,
        default=th.work_title_missing_warn_ratio,
    )
    p.add_argument(
        "--query-rewrite-min-per-page",
        type=float,
        default=th.query_rewrite_min_per_page,
    )
    p.add_argument(
        "--context-answer-skew-warn-ratio",
        type=float,
        default=th.context_answer_skew_warn_ratio,
    )
    # Phase 5.1 — heading preservation knobs
    p.add_argument(
        "--min-mean-section-count",
        type=float,
        default=th.min_mean_section_count,
    )
    p.add_argument(
        "--summary-skew-warn-ratio",
        type=float,
        default=th.summary_skew_warn_ratio,
    )
    p.add_argument(
        "--blank-section-title-warn-ratio",
        type=float,
        default=th.blank_section_title_warn_ratio,
    )
    p.add_argument(
        "--generic-section-title-warn-ratio",
        type=float,
        default=th.generic_section_title_warn_ratio,
    )
    p.add_argument(
        "--min-distinct-section-depths",
        type=int,
        default=th.min_distinct_section_depths,
    )
    p.add_argument(
        "--section-title-top-n",
        type=int,
        default=th.section_title_top_n,
    )

    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    pages_path = Path(args.pages)
    chunks_path = Path(args.chunks)
    manifest_path = Path(args.manifest) if args.manifest else None
    sft_path = Path(args.sft_report) if args.sft_report else None
    out_dir = Path(args.out_dir)

    for label, p in (("pages", pages_path), ("chunks", chunks_path)):
        if not p.exists():
            print(f"{label} not found: {p}", file=sys.stderr)
            return 2
    if manifest_path is not None and not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    if sft_path is not None and not sft_path.exists():
        print(f"sft-report not found: {sft_path}", file=sys.stderr)
        return 2

    pages = list(_iter_jsonl(pages_path))
    chunks = list(_iter_jsonl(chunks_path))

    manifest_obj = None
    if manifest_path is not None:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest_obj = manifest_from_dict(json.load(f))

    sft_report_obj = None
    if sft_path is not None:
        with sft_path.open("r", encoding="utf-8") as f:
            sft_report_obj = json.load(f)

    thresholds = AuditThresholds(
        too_short_chars=args.too_short_chars,
        too_long_chars=args.too_long_chars,
        work_skew_top_n=args.work_skew_top_n,
        work_skew_warn_ratio=args.work_skew_warn_ratio,
        short_chunk_warn_ratio=args.short_chunk_warn_ratio,
        unsupported_section_type_warn_ratio=args.unsupported_section_type_warn_ratio,
        aliases_missing_warn_ratio=args.aliases_missing_warn_ratio,
        fetched_at_missing_warn_ratio=args.fetched_at_missing_warn_ratio,
        work_title_missing_warn_ratio=args.work_title_missing_warn_ratio,
        query_rewrite_min_per_page=args.query_rewrite_min_per_page,
        context_answer_skew_warn_ratio=args.context_answer_skew_warn_ratio,
        min_mean_section_count=args.min_mean_section_count,
        summary_skew_warn_ratio=args.summary_skew_warn_ratio,
        blank_section_title_warn_ratio=args.blank_section_title_warn_ratio,
        generic_section_title_warn_ratio=args.generic_section_title_warn_ratio,
        min_distinct_section_depths=args.min_distinct_section_depths,
        section_title_top_n=args.section_title_top_n,
    )

    report = run_full_audit(
        pages=pages,
        chunks=chunks,
        manifest=manifest_obj,
        sft_report=sft_report_obj,
        thresholds=thresholds,
    )

    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{args.report_prefix}_report.json"
    md_path = out_dir / f"{args.report_prefix}_report.md"

    if not args.no_json:
        with json_path.open("w", encoding="utf-8") as f:
            json.dump(
                report.to_dict(),
                f,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
    if not args.no_markdown:
        md_path.write_text(render_markdown(report), encoding="utf-8")

    print(
        f"pages={len(pages)} chunks={len(chunks)} "
        f"manifest={'yes' if manifest_obj else 'no'} "
        f"sft={'yes' if sft_report_obj else 'no'}"
    )
    print(
        f"warnings: {len(report.warnings)} "
        f"(unsupported_section_type_ratio={report.pages.unsupported_section_type_ratio:.2%}, "
        f"too_short_ratio={report.chunks.too_short_ratio:.2%})"
    )
    for w in report.warnings:
        print(f"WARN: {w}", file=sys.stderr)
    if not args.no_json:
        print(f"wrote: {json_path}")
    if not args.no_markdown:
        print(f"wrote: {md_path}")
    if args.fail_on_warning and report.warnings:
        print(
            f"--fail-on-warning: {len(report.warnings)} warning(s) — exiting non-zero",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
