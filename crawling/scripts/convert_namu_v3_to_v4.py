"""CLI: convert namu_anime_v3.jsonl into v4 pages/chunks + validation report.

Usage::

    python -m scripts.convert_namu_v3_to_v4 \
        --input namu_anime_v3.jsonl \
        --out-dir eval/reports/namu-v4-migration

    python -m scripts.convert_namu_v3_to_v4 \
        --input namu_anime_v3.jsonl \
        --out-dir eval/reports/namu-v4-migration-smoke \
        --limit 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval.harness.dataset_v4_validation import render_markdown, validate
from eval.harness.namu_v3_to_v4 import convert_jsonl, write_jsonl


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Convert namu_anime v3 JSONL into v4 pages/chunks + validation report."
    )
    p.add_argument("--input", required=True, help="path to v3 JSONL (e.g. namu_anime_v3.jsonl)")
    p.add_argument(
        "--out-dir",
        required=True,
        help="output directory (will be created)",
    )
    p.add_argument(
        "--limit",
        type=int,
        default=None,
        help="optional cap on number of input v3 records (smoke runs)",
    )
    p.add_argument(
        "--max-warnings",
        type=int,
        default=2000,
        help="cap on the number of warnings stored in validation_report.json",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"input not found: {input_path}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pages, chunks, warnings, input_count = convert_jsonl(input_path, limit=args.limit)

    pages_path = out_dir / "pages_v4.jsonl"
    chunks_path = out_dir / "chunks_v4.jsonl"
    pages_n = write_jsonl(pages, pages_path)
    chunks_n = write_jsonl(chunks, chunks_path)

    capped_warnings = warnings[: args.max_warnings]
    report = validate(
        pages,
        chunks,
        input_count=input_count,
        extra_warnings=capped_warnings,
    )

    report_json_path = out_dir / "validation_report.json"
    report_md_path = out_dir / "validation_report.md"

    report_dict = report.to_dict()
    report_dict["warnings_total"] = len(warnings)
    report_dict["warnings_truncated"] = len(warnings) > len(capped_warnings)

    with report_json_path.open("w", encoding="utf-8") as f:
        json.dump(report_dict, f, ensure_ascii=False, indent=2)
    with report_md_path.open("w", encoding="utf-8") as f:
        f.write(render_markdown(report))

    print(
        f"input_records={input_count} pages={pages_n} chunks={chunks_n} "
        f"warnings={len(warnings)}"
    )
    print(f"wrote: {pages_path}")
    print(f"wrote: {chunks_path}")
    print(f"wrote: {report_json_path}")
    print(f"wrote: {report_md_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
