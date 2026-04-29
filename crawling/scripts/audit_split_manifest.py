"""CLI: re-audit an existing split manifest (Phase 3.5).

Usage::

    python -m scripts.audit_split_manifest \\
        --pages pages_v4.jsonl \\
        --chunks rag_chunks.jsonl \\
        --manifest split_manifest.json \\
        --out split_manifest.report.json

Loads ``split_manifest.json`` from disk, runs the leakage / grouping /
distribution audit against the provided pages (and optional chunks),
and writes a fresh ``split_report``. Useful when you want to re-audit
an existing or extended manifest without re-running the build step.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval.harness.split_manifest import audit_manifest, manifest_from_dict


def _iter_jsonl(path: Path):
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
            "Audit a split_manifest.json — leakage, grouping, distribution "
            "(plus chunk-level distribution when --chunks is given)."
        )
    )
    p.add_argument("--manifest", required=True, help="path to split_manifest.json")
    p.add_argument("--pages", required=True, help="path to v4 pages JSONL")
    p.add_argument(
        "--chunks",
        default=None,
        help="optional rag_chunks.jsonl for chunk-level distribution",
    )
    p.add_argument(
        "--out",
        required=True,
        help="output path for the audit report JSON",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest)
    pages_path = Path(args.pages)
    chunks_path = Path(args.chunks) if args.chunks else None
    out_path = Path(args.out)

    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 2
    if not pages_path.exists():
        print(f"pages not found: {pages_path}", file=sys.stderr)
        return 2
    if chunks_path is not None and not chunks_path.exists():
        print(f"chunks not found: {chunks_path}", file=sys.stderr)
        return 2

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = manifest_from_dict(json.load(f))

    pages = list(_iter_jsonl(pages_path))
    report = audit_manifest(
        manifest,
        pages=pages,
        chunks=(_iter_jsonl(chunks_path) if chunks_path else None),
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, ensure_ascii=False, indent=2, sort_keys=True)

    print(
        f"manifest={manifest_path} pages={len(pages)} chunks={chunks_path}"
    )
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
    print(f"wrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
