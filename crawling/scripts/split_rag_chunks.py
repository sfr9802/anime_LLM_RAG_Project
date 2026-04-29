"""CLI: apply a split_manifest to rag_chunks.jsonl, producing per-split files.

Usage::

    python -m scripts.split_rag_chunks \\
        --chunks data/rag_chunks.jsonl \\
        --manifest data/split_manifest.json \\
        --out-dir data

Writes ``<out-dir>/rag_chunks.train.jsonl``,
``rag_chunks.valid.jsonl``, ``rag_chunks.test.jsonl``. Each chunk is
preserved verbatim — only the doc_id is consulted for routing.

By default the CLI errors on the first chunk whose ``doc_id`` is not in
the manifest. Use ``--allow-missing-docs`` to silently drop unknown
chunks; their doc_ids are listed in the printed summary.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterator

from eval.harness.split_manifest import (
    SPLIT_NAMES,
    apply_manifest_to_chunks_iter,
    manifest_from_dict,
)


def _iter_chunks_jsonl(path: Path) -> Iterator[dict]:
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
            "Apply a split_manifest.json to a rag_chunks.jsonl, producing "
            "rag_chunks.train.jsonl / rag_chunks.valid.jsonl / "
            "rag_chunks.test.jsonl. Routing is doc_id-based and never "
            "splits a doc across files."
        )
    )
    p.add_argument(
        "--chunks",
        required=True,
        help="path to rag_chunks.jsonl",
    )
    p.add_argument(
        "--manifest",
        required=True,
        help="path to split_manifest.json (produced by scripts.build_split_manifest)",
    )
    p.add_argument(
        "--out-dir",
        required=True,
        help="output directory for rag_chunks.{train,valid,test}.jsonl",
    )
    p.add_argument(
        "--allow-missing-docs",
        action="store_true",
        help=(
            "drop chunks whose doc_id is not in the manifest. Without this "
            "flag, the first such chunk causes the run to abort."
        ),
    )
    p.add_argument(
        "--prefix",
        default="rag_chunks",
        help=(
            "filename prefix for output files (default: %(default)s). The "
            "split name and .jsonl extension are appended."
        ),
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    chunks_path = Path(args.chunks)
    manifest_path = Path(args.manifest)
    out_dir = Path(args.out_dir)

    if not chunks_path.exists():
        print(f"chunks not found: {chunks_path}", file=sys.stderr)
        return 2
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 2

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = manifest_from_dict(json.load(f))

    out_dir.mkdir(parents=True, exist_ok=True)
    out_paths = {
        s: out_dir / f"{args.prefix}.{s}.jsonl" for s in SPLIT_NAMES
    }
    counts = {s: 0 for s in SPLIT_NAMES}
    missing = 0
    missing_doc_ids: set = set()

    handles = {s: out_paths[s].open("w", encoding="utf-8") for s in SPLIT_NAMES}
    try:
        chunks_iter = _iter_chunks_jsonl(chunks_path)
        try:
            for split, chunk in apply_manifest_to_chunks_iter(
                chunks_iter,
                manifest,
                allow_missing=args.allow_missing_docs,
            ):
                handles[split].write(json.dumps(chunk, ensure_ascii=False))
                handles[split].write("\n")
                counts[split] += 1
        except ValueError as exc:
            print(f"split failed: {exc}", file=sys.stderr)
            return 2

        if args.allow_missing_docs:
            # Re-walk to count drops cheaply (the iterator dropped them
            # silently). The cost is one extra pass; acceptable since the
            # alternative is to hold the result in memory.
            doc_to_split = {
                d: s for s in SPLIT_NAMES for d in manifest.doc_ids.get(s, [])
            }
            for chunk in _iter_chunks_jsonl(chunks_path):
                d = chunk.get("doc_id")
                if isinstance(d, str) and d and d not in doc_to_split:
                    missing += 1
                    missing_doc_ids.add(d)
    finally:
        for h in handles.values():
            h.close()

    print(
        f"chunks={chunks_path} manifest={manifest_path} "
        f"allow_missing_docs={args.allow_missing_docs}"
    )
    for s in SPLIT_NAMES:
        print(f"  {s}: {counts[s]} chunks -> {out_paths[s]}")
    if args.allow_missing_docs and missing:
        sample = sorted(missing_doc_ids)[:5]
        print(
            f"  missing: {missing} chunks dropped "
            f"({len(missing_doc_ids)} unique doc_ids; sample={sample})"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
