"""CLI: extend an existing split manifest with new groups discovered in a v4 pages JSONL.

Usage::

    python -m scripts.extend_split_manifest \\
        --input pages_v4.jsonl \\
        --base-manifest split_manifest.json \\
        --out split_manifest.extended.json \\
        --seed 42

Behaviour (Phase 3.5 §3):

* Groups already in the base manifest keep their split assignment.
* Groups only present in the current input are routed deterministically
  to whichever split has the largest ratio deficit (seeded shuffle for
  iteration order; canonical ``train > valid > test`` tie-break).
* Groups in the base manifest but missing from the current input are
  kept by default — pass ``--drop-missing-docs`` to remove them, plus
  any base docs that are no longer in the current input.
* The extended manifest re-runs the leakage / coverage audit;
  ``--chunks rag_chunks.jsonl`` enriches the report with chunk
  distribution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval.harness.split_manifest import (
    DEFAULT_SEED,
    audit_manifest,
    extend_split_manifest,
    manifest_from_dict,
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
            "Extend an existing split_manifest.json with new groups "
            "discovered in a v4 pages JSONL. Existing group/split "
            "assignments are preserved verbatim; only new groups are "
            "(re)allocated."
        )
    )
    p.add_argument("--input", required=True, help="path to v4 pages JSONL")
    p.add_argument(
        "--base-manifest",
        required=True,
        help="path to the existing split_manifest.json to extend",
    )
    p.add_argument(
        "--out", required=True, help="output path for the extended manifest"
    )
    p.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="seed for the deterministic new-group shuffle (default: %(default)s)",
    )
    p.add_argument(
        "--drop-missing-docs",
        action="store_true",
        help=(
            "drop doc_ids and group_ids that are present in the base "
            "manifest but absent from the current input. By default, "
            "missing entries are preserved and reported only."
        ),
    )
    p.add_argument(
        "--chunks",
        default=None,
        help="optional rag_chunks.jsonl for the post-extension distribution audit",
    )
    p.add_argument(
        "--report-out",
        default=None,
        help=(
            "output path for the audit report JSON. Defaults to "
            "<out>.report.json. Ignored when --no-report is set."
        ),
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="skip writing the audit report",
    )
    p.add_argument(
        "--max-fallback-ratio",
        type=float,
        default=None,
        help="warn when work_id-fallback ratio exceeds this threshold",
    )
    p.add_argument(
        "--fail-on-high-fallback",
        action="store_true",
        help="exit non-zero when --max-fallback-ratio is exceeded",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    base_manifest_path = Path(args.base_manifest)
    out_path = Path(args.out)
    chunks_path = Path(args.chunks) if args.chunks else None

    if not input_path.exists():
        print(f"input not found: {input_path}", file=sys.stderr)
        return 2
    if not base_manifest_path.exists():
        print(f"base manifest not found: {base_manifest_path}", file=sys.stderr)
        return 2
    if chunks_path is not None and not chunks_path.exists():
        print(f"chunks not found: {chunks_path}", file=sys.stderr)
        return 2

    with base_manifest_path.open("r", encoding="utf-8") as f:
        base_manifest = manifest_from_dict(json.load(f))

    pages = list(_iter_pages_jsonl(input_path))
    try:
        manifest, extension = extend_split_manifest(
            pages,
            base_manifest,
            seed=args.seed,
            drop_missing_docs=args.drop_missing_docs,
            max_fallback_ratio=args.max_fallback_ratio,
            fail_on_high_fallback=args.fail_on_high_fallback,
        )
    except ValueError as exc:
        print(f"extend_split_manifest failed: {exc}", file=sys.stderr)
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(manifest.to_dict(), f, ensure_ascii=False, indent=2, sort_keys=True)

    print(
        f"input={input_path} pages={len(pages)} seed={args.seed} "
        f"drop_missing_docs={args.drop_missing_docs}"
    )
    print(
        f"extension: base={extension.base_groups} new={extension.new_groups} "
        f"preserved={extension.preserved_groups} "
        f"missing={len(extension.missing_groups_from_input)}"
    )
    for s in ("train", "valid", "test"):
        added = extension.added_groups.get(s, [])
        if added:
            print(f"  added {len(added)} new group(s) to {s}")
    print(
        f"groups: train={manifest.counts.groups.train} "
        f"valid={manifest.counts.groups.valid} "
        f"test={manifest.counts.groups.test} "
        f"total={manifest.counts.groups.total}"
    )
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
            extension=extension,
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, ensure_ascii=False, indent=2, sort_keys=True)
        print(
            f"audit: doc_overlap={len(report.leakage.doc_id_overlap)} "
            f"group_overlap={len(report.leakage.group_id_overlap)} "
            f"warnings={len(report.warnings)}"
        )
        print(f"wrote: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
