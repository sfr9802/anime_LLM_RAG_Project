"""CLI: build a doc_id-level split manifest from a v4 pages JSONL.

Usage::

    python -m scripts.build_split_manifest \\
        --input eval/reports/namu-v4-migration-smoke/pages_v4.jsonl \\
        --out data/split_manifest.json \\
        --seed 42 \\
        --train-ratio 0.8 \\
        --valid-ratio 0.1 \\
        --test-ratio 0.1

Always writes a leakage / coverage audit alongside the manifest. By
default the report path is derived from ``--out`` by replacing the
``.json`` suffix with ``.report.json``; use ``--report-out`` to override
or ``--no-report`` to skip the report entirely.

Phase 3.5 additions:

* ``--chunks rag_chunks.jsonl`` enriches the report with per-split chunk
  count, ``section_type`` distribution, and chunks-per-group stats.
* ``--max-fallback-ratio`` thresholds the work_id-fallback ratio. By
  default (no flag) the threshold is disabled. Set a value (e.g.
  ``0.05``) to log a warning when too many docs are missing ``work_id``;
  add ``--fail-on-high-fallback`` to turn that warning into an error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval.harness.split_manifest import (
    DEFAULT_SEED,
    DEFAULT_TEST_RATIO,
    DEFAULT_TRAIN_RATIO,
    DEFAULT_VALID_RATIO,
    audit_manifest,
    build_split_manifest,
)


def _iter_pages_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _iter_chunks_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _default_report_path(manifest_path: Path) -> Path:
    if manifest_path.suffix == ".json":
        return manifest_path.with_suffix(".report.json")
    return manifest_path.with_name(manifest_path.name + ".report.json")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Build a deterministic group-level split manifest from a v4 pages "
            "JSONL. Splits at the work_id (group) boundary so a work's main + "
            "subpages always land in the same split (no chunk-level random "
            "split — that would leak proper nouns across train/test)."
        )
    )
    p.add_argument(
        "--input",
        required=True,
        help="path to v4 pages JSONL (raw_documents.jsonl / pages_v4.jsonl)",
    )
    p.add_argument(
        "--out",
        required=True,
        help="output path for split_manifest.json",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="RNG seed for the deterministic group shuffle (default: %(default)s)",
    )
    p.add_argument(
        "--train-ratio",
        type=float,
        default=DEFAULT_TRAIN_RATIO,
        help="train ratio (default: %(default)s)",
    )
    p.add_argument(
        "--valid-ratio",
        type=float,
        default=DEFAULT_VALID_RATIO,
        help="valid ratio (default: %(default)s)",
    )
    p.add_argument(
        "--test-ratio",
        type=float,
        default=DEFAULT_TEST_RATIO,
        help="test ratio (default: %(default)s)",
    )
    p.add_argument(
        "--report-out",
        default=None,
        help=(
            "output path for the audit report JSON. Defaults to <out>.report.json. "
            "Ignored when --no-report is set."
        ),
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="skip writing the audit report",
    )
    p.add_argument(
        "--chunks",
        default=None,
        help=(
            "optional path to rag_chunks.jsonl. When provided, the audit "
            "report includes chunks-per-split, section_type distribution, "
            "and chunks-per-group statistics."
        ),
    )
    p.add_argument(
        "--max-fallback-ratio",
        type=float,
        default=None,
        help=(
            "warn when the share of docs missing work_id (i.e. routed via the "
            "page_id fallback) exceeds this threshold. Default: disabled."
        ),
    )
    p.add_argument(
        "--fail-on-high-fallback",
        action="store_true",
        help=(
            "exit with a non-zero status when --max-fallback-ratio is exceeded. "
            "No-op without --max-fallback-ratio."
        ),
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"input not found: {input_path}", file=sys.stderr)
        return 2
    out_path = Path(args.out)

    chunks_path = Path(args.chunks) if args.chunks else None
    if chunks_path is not None and not chunks_path.exists():
        print(f"chunks not found: {chunks_path}", file=sys.stderr)
        return 2

    pages = list(_iter_pages_jsonl(input_path))
    try:
        manifest = build_split_manifest(
            pages,
            seed=args.seed,
            train_ratio=args.train_ratio,
            valid_ratio=args.valid_ratio,
            test_ratio=args.test_ratio,
            max_fallback_ratio=args.max_fallback_ratio,
            fail_on_high_fallback=args.fail_on_high_fallback,
        )
    except ValueError as exc:
        print(f"build_split_manifest failed: {exc}", file=sys.stderr)
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, ensure_ascii=False, indent=2, sort_keys=True)

    print(
        f"input={input_path} pages={len(pages)} seed={args.seed} "
        f"ratios=({args.train_ratio}, {args.valid_ratio}, {args.test_ratio})"
    )
    print(
        f"groups: train={manifest.counts.groups.train} "
        f"valid={manifest.counts.groups.valid} "
        f"test={manifest.counts.groups.test} "
        f"total={manifest.counts.groups.total}"
    )
    print(
        f"docs  : train={manifest.counts.docs.train} "
        f"valid={manifest.counts.docs.valid} "
        f"test={manifest.counts.docs.test} "
        f"total={manifest.counts.docs.total}"
    )
    if manifest.fallback_group_count:
        print(f"fallback groups (page_id-as-group): {manifest.fallback_group_count}")
    if manifest.grouping is not None:
        print(
            f"work_id coverage: {manifest.grouping.work_id_coverage_ratio:.4f} "
            f"({manifest.grouping.work_id_present_docs}/"
            f"{manifest.grouping.total_docs})"
        )
    for w in manifest.warnings:
        print(f"WARN: {w}", file=sys.stderr)
    print(f"wrote: {out_path}")

    if not args.no_report:
        report_path = (
            Path(args.report_out) if args.report_out else _default_report_path(out_path)
        )
        report = audit_manifest(
            manifest,
            pages=pages,
            chunks=(_iter_chunks_jsonl(chunks_path) if chunks_path else None),
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2, sort_keys=True)
        print(
            f"audit: doc_overlap={len(report.leakage.doc_id_overlap)} "
            f"group_overlap={len(report.leakage.group_id_overlap)} "
            f"warnings={len(report.warnings)}"
        )
        if report.distribution is not None and chunks_path is not None:
            print(
                f"  chunks: train={report.distribution.chunks.get('train', 0)} "
                f"valid={report.distribution.chunks.get('valid', 0)} "
                f"test={report.distribution.chunks.get('test', 0)}"
            )
        print(f"wrote: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
