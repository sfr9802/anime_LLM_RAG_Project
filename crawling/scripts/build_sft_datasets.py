"""CLI: build SFT JSONL datasets (Phase 4).

Usage::

    python -m scripts.build_sft_datasets \\
        --pages data/raw_documents.jsonl \\
        --chunks data/rag_chunks.jsonl \\
        --manifest data/split_manifest.json \\
        --out-dir data/sft \\
        --max-records-per-split 1000

Writes six JSONL files alongside an ``sft_export_report.json``::

    <out-dir>/sft_query_rewrite.{train,valid,test}.jsonl
    <out-dir>/sft_context_answer.{train,valid,test}.jsonl
    <out-dir>/sft_export_report.json

Routing is split-aware: a chunk's split is determined entirely by the
manifest's ``doc_to_group`` / ``doc_ids`` mapping. Chunks whose
``doc_id`` is missing from the manifest cause a fail-fast abort by
default; pass ``--allow-missing-docs`` to drop them silently and bump
the ``missing_manifest`` counter in the report instead.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterator

from eval.harness.qa_candidate_extractor import (
    QUESTION_TEMPLATES_BY_SECTION,
)
from eval.harness.sft_context_answer_export import (
    DEFAULT_MIN_CONTEXT_CHARS,
    build_context_answer_record,
    is_low_quality_metadata,
)
from eval.harness.sft_query_rewrite_export import (
    USER_QUERY_TEMPLATES,
    build_doc_meta_lookup,
    build_query_rewrite_record,
)
from eval.harness.sft_schema import (
    SFTExportReport,
    SFTSkipped,
    SFTSplitCounts,
)
from eval.harness.split_manifest import SPLIT_NAMES, manifest_from_dict


def _iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
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
            "Build messages-format SFT JSONL datasets (query_rewrite + "
            "context_answer) split-aware via split_manifest.json. Uses "
            "rule-based templates only — no LLM calls."
        )
    )
    p.add_argument("--pages", required=True, help="path to v4 pages JSONL")
    p.add_argument("--chunks", required=True, help="path to rag_chunks.jsonl")
    p.add_argument("--manifest", required=True, help="path to split_manifest.json")
    p.add_argument("--out-dir", required=True, help="output directory")
    p.add_argument(
        "--max-records-per-split",
        type=int,
        default=None,
        help=(
            "cap the number of records per (output type, split). Applied "
            "independently to query_rewrite and context_answer. Default: no cap."
        ),
    )
    p.add_argument(
        "--min-context-chars",
        type=int,
        default=DEFAULT_MIN_CONTEXT_CHARS,
        help="minimum chunk_text length to consider (default: %(default)s)",
    )
    p.add_argument(
        "--include-low-quality",
        action="store_true",
        help="do not skip is_stub / is_table_like / too-short chunks",
    )
    p.add_argument(
        "--only-query-rewrite",
        action="store_true",
        help="only emit query_rewrite records; context_answer files stay empty",
    )
    p.add_argument(
        "--only-context-answer",
        action="store_true",
        help="only emit context_answer records; query_rewrite files stay empty",
    )
    p.add_argument(
        "--allow-missing-docs",
        action="store_true",
        help=(
            "drop chunks whose doc_id is not in the manifest. Without this "
            "flag, the first such chunk causes fail-fast (the spec default)."
        ),
    )
    p.add_argument(
        "--report-out",
        default=None,
        help=(
            "output path for sft_export_report.json. Default: "
            "<out-dir>/sft_export_report.json. Ignored when --no-report is set."
        ),
    )
    p.add_argument(
        "--no-report",
        action="store_true",
        help="skip writing the export report",
    )
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    if args.only_query_rewrite and args.only_context_answer:
        print(
            "--only-query-rewrite and --only-context-answer are mutually exclusive",
            file=sys.stderr,
        )
        return 2

    pages_path = Path(args.pages)
    chunks_path = Path(args.chunks)
    manifest_path = Path(args.manifest)
    out_dir = Path(args.out_dir)

    for label, p in (
        ("pages", pages_path),
        ("chunks", chunks_path),
        ("manifest", manifest_path),
    ):
        if not p.exists():
            print(f"{label} not found: {p}", file=sys.stderr)
            return 2

    with manifest_path.open("r", encoding="utf-8") as f:
        manifest = manifest_from_dict(json.load(f))
    doc_to_split: Dict[str, str] = {
        d: s for s in SPLIT_NAMES for d in manifest.doc_ids.get(s, [])
    }

    pages = list(_iter_jsonl(pages_path))
    doc_meta = build_doc_meta_lookup(pages)

    out_dir.mkdir(parents=True, exist_ok=True)
    qr_paths = {s: out_dir / f"sft_query_rewrite.{s}.jsonl" for s in SPLIT_NAMES}
    ca_paths = {s: out_dir / f"sft_context_answer.{s}.jsonl" for s in SPLIT_NAMES}
    qr_handles = {s: qr_paths[s].open("w", encoding="utf-8") for s in SPLIT_NAMES}
    ca_handles = {s: ca_paths[s].open("w", encoding="utf-8") for s in SPLIT_NAMES}

    counts_qr = SFTSplitCounts()
    counts_ca = SFTSplitCounts()
    skipped = SFTSkipped()
    section_dist_qr: Dict[str, "Counter"] = {s: Counter() for s in SPLIT_NAMES}
    section_dist_ca: Dict[str, "Counter"] = {s: Counter() for s in SPLIT_NAMES}
    seen_qr_queries: Dict[str, set] = {s: set() for s in SPLIT_NAMES}
    warnings: list = []

    do_qr = not args.only_context_answer
    do_ca = not args.only_query_rewrite

    cap = args.max_records_per_split

    def _qr_count(split: str) -> int:
        return getattr(counts_qr, split)

    def _ca_count(split: str) -> int:
        return getattr(counts_ca, split)

    def _bump_qr(split: str) -> None:
        setattr(counts_qr, split, getattr(counts_qr, split) + 1)

    def _bump_ca(split: str) -> None:
        setattr(counts_ca, split, getattr(counts_ca, split) + 1)

    try:
        for chunk in _iter_jsonl(chunks_path):
            if not isinstance(chunk, dict):
                continue
            doc_id_raw = chunk.get("doc_id")
            if not isinstance(doc_id_raw, str) or not doc_id_raw.strip():
                continue
            doc_id = doc_id_raw.strip()
            split = doc_to_split.get(doc_id)
            if split is None:
                if args.allow_missing_docs:
                    skipped.missing_manifest += 1
                    continue
                print(
                    f"chunk doc_id {doc_id!r} not in manifest "
                    f"(use --allow-missing-docs to drop)",
                    file=sys.stderr,
                )
                return 2

            if not args.include_low_quality:
                low, reason = is_low_quality_metadata(
                    chunk.get("metadata"), min_chars=args.min_context_chars
                )
                if low:
                    if reason == "low_quality":
                        skipped.low_quality += 1
                    elif reason == "too_short":
                        skipped.too_short += 1
                    continue

            meta = doc_meta.get(doc_id)
            if meta is None:
                # Manifest knows this doc, but pages_v4 doesn't carry it.
                # Surface as a warning rather than silently dropping; the
                # chunk has no usable title so neither exporter can emit.
                warnings.append(
                    f"doc_id {doc_id!r} present in manifest but missing from pages_v4; chunk skipped"
                )
                continue

            section_type = chunk.get("section_type", "other")

            # Query rewrite -------------------------------------------------
            if do_qr and (cap is None or _qr_count(split) < cap):
                qr_record = build_query_rewrite_record(
                    chunk, doc_meta=meta, split=split
                )
                if qr_record is None:
                    if section_type not in USER_QUERY_TEMPLATES:
                        skipped.unsupported_section_type += 1
                else:
                    user_query = qr_record.messages[1].content
                    if user_query not in seen_qr_queries[split]:
                        seen_qr_queries[split].add(user_query)
                        qr_handles[split].write(
                            json.dumps(qr_record.to_dict(), ensure_ascii=False)
                        )
                        qr_handles[split].write("\n")
                        _bump_qr(split)
                        if isinstance(section_type, str):
                            section_dist_qr[split][section_type] += 1

            # Context answer ----------------------------------------------
            if do_ca and (cap is None or _ca_count(split) < cap):
                ca_record = build_context_answer_record(
                    chunk,
                    doc_meta=meta,
                    split=split,
                    min_context_chars=args.min_context_chars,
                )
                if ca_record is None:
                    if section_type not in QUESTION_TEMPLATES_BY_SECTION:
                        skipped.unsupported_section_type += 1
                    else:
                        skipped.missing_evidence += 1
                else:
                    ca_handles[split].write(
                        json.dumps(ca_record.to_dict(), ensure_ascii=False)
                    )
                    ca_handles[split].write("\n")
                    _bump_ca(split)
                    if isinstance(section_type, str):
                        section_dist_ca[split][section_type] += 1
    finally:
        for h in list(qr_handles.values()) + list(ca_handles.values()):
            h.close()

    # ------------------------------------------------------------------ report
    report = SFTExportReport(
        counts={
            "query_rewrite": counts_qr,
            "context_answer": counts_ca,
        },
        skipped=skipped,
        section_type_distribution={
            "query_rewrite": {
                s: dict(section_dist_qr[s]) for s in SPLIT_NAMES
            },
            "context_answer": {
                s: dict(section_dist_ca[s]) for s in SPLIT_NAMES
            },
        },
        warnings=warnings,
    )

    print(
        f"pages={len(pages)} manifest={manifest_path} "
        f"out_dir={out_dir} only_qr={args.only_query_rewrite} "
        f"only_ca={args.only_context_answer}"
    )
    for kind, counts, paths in (
        ("query_rewrite", counts_qr, qr_paths),
        ("context_answer", counts_ca, ca_paths),
    ):
        print(
            f"  {kind}: train={counts.train} valid={counts.valid} test={counts.test}"
        )
        for s in SPLIT_NAMES:
            print(f"    {paths[s]}")
    print(f"  skipped: {skipped.to_dict()}")
    for w in warnings[:5]:
        print(f"WARN: {w}", file=sys.stderr)

    if not args.no_report:
        report_path = (
            Path(args.report_out)
            if args.report_out
            else out_dir / "sft_export_report.json"
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as f:
            json.dump(
                report.to_dict(),
                f,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        print(f"wrote report: {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
