"""CLI: export RAG chunks (rag_chunks.jsonl) from a v4 pages JSONL.

Usage::

    python -m scripts.export_rag_chunks \\
        --input eval/reports/namu-v4-migration-smoke/pages_v4.jsonl \\
        --out data/rag_chunks.jsonl \\
        --embedding-text-variant title_section

The defaults match the Phase 1 migration outputs so a typical run is::

    python -m scripts.export_rag_chunks \\
        --input eval/reports/namu-v4-migration/pages_v4.jsonl \\
        --out eval/reports/namu-v4-migration/rag_chunks.jsonl \\
        --embedding-text-variant title_section_alias
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from eval.harness.rag_chunk_export import (
    DEFAULT_EMBEDDING_TEXT_VARIANT,
    DEFAULT_MIN_CHARS,
    export_jsonl,
)
from eval.harness.rag_chunk_schema import EMBEDDING_TEXT_VARIANTS


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Export RAG chunks (rag_chunks.jsonl) from a v4 pages JSONL "
            "(e.g. pages_v4.jsonl produced by scripts.convert_namu_v3_to_v4)."
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
        help="output path for rag_chunks.jsonl",
    )
    p.add_argument(
        "--embedding-text-variant",
        choices=EMBEDDING_TEXT_VARIANTS,
        default=DEFAULT_EMBEDDING_TEXT_VARIANT,
        help=(
            "embedding_text format: raw | title | title_section | "
            "title_section_alias (default: %(default)s)"
        ),
    )
    p.add_argument(
        "--min-chars",
        type=int,
        default=DEFAULT_MIN_CHARS,
        help=(
            "minimum chunk_text length; chunks shorter than this are dropped "
            "unless --include-low-quality is set (default: %(default)s)"
        ),
    )
    p.add_argument(
        "--include-low-quality",
        action="store_true",
        help=(
            "include sections flagged as stub / table_like / below min_chars. "
            "list_like sections are always included regardless."
        ),
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"input not found: {input_path}", file=sys.stderr)
        return 2
    output_path = Path(args.out)

    n = export_jsonl(
        input_path,
        output_path,
        embedding_text_variant=args.embedding_text_variant,
        min_chars=args.min_chars,
        include_low_quality=args.include_low_quality,
    )
    print(
        f"input={input_path} variant={args.embedding_text_variant} "
        f"min_chars={args.min_chars} include_low_quality={args.include_low_quality}"
    )
    print(f"wrote: {output_path} ({n} chunks)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
