"""Tests for the Phase 4 SFT JSONL exporter (rule-based, split-aware).

Covers:
* qa_candidate_extractor — evidence_span / question template rules
* sft_query_rewrite_export — messages format, JSON payload, dedup
* sft_context_answer_export — context+question user, evidence answer
* split leakage — train/valid/test isolation, missing-doc fail-fast
* build_sft_datasets CLI — 6-file output, --only-* flags, report
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from eval.harness.qa_candidate_extractor import (
    QUESTION_TEMPLATES_BY_SECTION,
    extract_qa_candidate,
    first_evidence_span,
    supported_section_types,
)
from eval.harness.sft_context_answer_export import (
    DEFAULT_MIN_CONTEXT_CHARS,
    build_context_answer_record,
    is_low_quality_metadata,
    iter_context_answer_records,
)
from eval.harness.sft_query_rewrite_export import (
    DocMeta,
    SECTION_TYPE_FILTERS,
    USER_QUERY_TEMPLATES,
    build_doc_meta_lookup,
    build_query_rewrite_record,
    iter_query_rewrite_records,
)
from eval.harness.sft_schema import (
    SCHEMA_VERSION_SFT_CONTEXT_ANSWER,
    SCHEMA_VERSION_SFT_EXPORT_REPORT,
    SCHEMA_VERSION_SFT_QUERY_REWRITE,
    ROLE_ASSISTANT,
    ROLE_SYSTEM,
    ROLE_USER,
    SFTRecord,
)
from eval.harness.split_manifest import SPLIT_NAMES, build_split_manifest
from scripts.build_sft_datasets import main as sft_main


# ---------------------------------------------------------------- fixtures


def _page(
    *,
    page_id: str,
    work_id: str,
    work_title: str,
    page_title: str = None,
    page_type: str = "work",
    aliases: List[str] = None,
) -> Dict[str, Any]:
    return {
        "schema_version": "namu_anime_v4_page",
        "page_id": page_id,
        "work_id": work_id,
        "work_title": work_title,
        "page_title": page_title or work_title,
        "page_type": page_type,
        "relation": "main" if page_type == "work" else page_type,
        "aliases": aliases or [],
    }


def _chunk(
    *,
    doc_id: str,
    chunk_id: str = None,
    section_type: str = "summary",
    chunk_text: str = None,
    section_id: str = None,
    section_key: str = None,
    is_stub: bool = False,
    is_table_like: bool = False,
    text_length: int = None,
) -> Dict[str, Any]:
    if chunk_text is None:
        chunk_text = (
            "이 작품은 2010년대 일본에서 시작된 인기 시리즈다. 본 작품의 첫 시즌은 호평을 받았다. "
            "이후 후속 시즌이 제작되었다."
        )
    md_text_length = text_length if text_length is not None else len(chunk_text)
    return {
        "schema_version": "namu_anime_v4_rag_chunk",
        "chunk_id": chunk_id or f"c_{doc_id}_{section_type}",
        "doc_id": doc_id,
        "title": doc_id,
        "aliases": [],
        "section_id": section_id or f"sid_{doc_id}_{section_type}",
        "section_key": section_key or f"sk_{doc_id}_{section_type}",
        "section_path": ["본문"],
        "section_type": section_type,
        "chunk_text": chunk_text,
        "embedding_text": chunk_text,
        "metadata": {
            "source_url": None,
            "crawl_version": "v4",
            "has_spoiler": False,
            "text_length": md_text_length,
            "noise_score": 0.0,
            "is_stub": is_stub,
            "is_table_like": is_table_like,
            "is_list_like": False,
        },
    }


def _build_corpus(n_works: int = 6, sections_per_work: int = 3) -> tuple:
    pages: List[Dict[str, Any]] = []
    chunks: List[Dict[str, Any]] = []
    section_types_pool = ("summary", "character", "setting")
    for i in range(n_works):
        page_id = f"p{i}"
        work_id = f"w{i}"
        work_title = f"작품_{i}"
        pages.append(
            _page(
                page_id=page_id,
                work_id=work_id,
                work_title=work_title,
                aliases=[f"별칭_{i}"],
            )
        )
        for j in range(sections_per_work):
            stype = section_types_pool[j % len(section_types_pool)]
            chunks.append(
                _chunk(
                    doc_id=page_id,
                    chunk_id=f"c{i}_{j}",
                    section_type=stype,
                    section_key=f"sk{i}_{j}",
                    section_id=f"sid{i}_{j}",
                )
            )
    return pages, chunks


def _write_jsonl(path: Path, items: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _write_manifest(path: Path, manifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# ---------------------------------------------------------------- qa_candidate_extractor


def test_first_evidence_span_returns_first_sentence():
    text = "첫 문장이다. 두 번째 문장은 별개. 세 번째 문장."
    span = first_evidence_span(text, min_chars=5)
    assert span == "첫 문장이다."


def test_first_evidence_span_truncates_when_no_terminator():
    text = "x" * 600
    span = first_evidence_span(text, min_chars=30, max_chars=200)
    assert len(span) <= 200


def test_first_evidence_span_returns_empty_for_empty():
    assert first_evidence_span("") == ""
    assert first_evidence_span("   ") == ""


def test_extract_qa_candidate_uses_section_type_template():
    chunk_text = (
        "본 작품은 2020년에 방영을 시작한 인기 시리즈이다. "
        "메인 주인공은 가족의 비극을 겪고 모험을 떠난다. "
        "이후 동료를 만나며 성장한다."
    )
    qa = extract_qa_candidate(
        title="귀멸의 칼날",
        section_type="summary",
        chunk_text=chunk_text,
    )
    assert qa is not None
    assert "귀멸의 칼날" in qa.question
    assert qa.evidence_span in chunk_text
    assert qa.answer == qa.evidence_span


def test_extract_qa_candidate_rejects_unsupported_section_type():
    chunk_text = (
        "이 텍스트는 충분히 긴 문장으로 구성된 테스트 데이터이다. "
        "추가로 더 많은 문장이 이어진다. 마지막 문장도 있다."
    )
    qa = extract_qa_candidate(
        title="작품A",
        section_type="other",
        chunk_text=chunk_text,
    )
    assert qa is None


def test_extract_qa_candidate_rejects_short_chunk_text():
    qa = extract_qa_candidate(
        title="작품A",
        section_type="summary",
        chunk_text="짧다",
        min_chars=60,
    )
    assert qa is None


def test_extract_qa_candidate_rejects_blank_title():
    chunk_text = "본 작품은 2020년에 방영을 시작한 인기 시리즈이다. 다른 문장도 따라온다."
    qa = extract_qa_candidate(
        title="",
        section_type="summary",
        chunk_text=chunk_text,
    )
    assert qa is None


def test_supported_section_types_consistent():
    types = supported_section_types()
    assert "summary" in types
    assert "character" in types
    assert "other" not in types
    # Templates and supported types must agree
    assert set(types) == set(QUESTION_TEMPLATES_BY_SECTION.keys())


# ---------------------------------------------------------------- query_rewrite


def test_query_rewrite_record_has_messages_format():
    chunk = _chunk(doc_id="p0", section_type="summary")
    meta = DocMeta(work_title="작품_0", page_title="작품_0", aliases=[])
    rec = build_query_rewrite_record(chunk, doc_meta=meta, split="train")
    assert rec is not None
    assert rec.schema_version == SCHEMA_VERSION_SFT_QUERY_REWRITE
    roles = [m.role for m in rec.messages]
    assert roles == [ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT]


def test_query_rewrite_assistant_is_valid_json():
    chunk = _chunk(doc_id="p0", section_type="setting")
    meta = DocMeta(work_title="귀멸의 칼날", page_title="귀멸의 칼날", aliases=["Demon Slayer"])
    rec = build_query_rewrite_record(chunk, doc_meta=meta, split="train")
    assert rec is not None
    payload = json.loads(rec.messages[2].content)
    assert isinstance(payload, dict)
    assert payload["normalized_query"]
    assert payload["filters"]["title"] == "귀멸의 칼날"
    assert "setting" in payload["filters"]["section_type"]
    # entities should include alias
    assert "Demon Slayer" in payload["entities"]


def test_query_rewrite_filters_contain_title_and_section_type():
    chunk = _chunk(doc_id="p0", section_type="character")
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_query_rewrite_record(chunk, doc_meta=meta, split="valid")
    payload = json.loads(rec.messages[2].content)
    assert "title" in payload["filters"]
    assert "section_type" in payload["filters"]
    assert payload["filters"]["section_type"] == SECTION_TYPE_FILTERS["character"]


def test_query_rewrite_normalized_query_not_empty():
    chunk = _chunk(doc_id="p0", section_type="summary")
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_query_rewrite_record(chunk, doc_meta=meta, split="train")
    payload = json.loads(rec.messages[2].content)
    assert payload["normalized_query"]
    assert "작품A" in payload["normalized_query"]


def test_query_rewrite_source_includes_split():
    chunk = _chunk(doc_id="p0", section_type="summary", chunk_id="c0")
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_query_rewrite_record(chunk, doc_meta=meta, split="test")
    src = rec.source.to_dict()
    assert src["split"] == "test"
    assert src["doc_id"] == "p0"
    assert src["chunk_id"] == "c0"
    assert "evidence_span" not in src  # query_rewrite has no evidence


def test_query_rewrite_returns_none_for_unsupported_section_type():
    chunk = _chunk(doc_id="p0", section_type="other")
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_query_rewrite_record(chunk, doc_meta=meta, split="train")
    assert rec is None


def test_query_rewrite_iterator_dedupes_per_split():
    """Two chunks of the same (doc, section_type) collapse to one record."""
    pages, chunks = _build_corpus(n_works=2, sections_per_work=2)
    # Force both chunks under the same doc + section_type
    chunks = [
        _chunk(doc_id="p0", chunk_id="c0a", section_type="summary"),
        _chunk(doc_id="p0", chunk_id="c0b", section_type="summary"),
    ]
    pages = [_page(page_id="p0", work_id="w0", work_title="작품_0")]
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0
    )
    meta = build_doc_meta_lookup(pages)
    pairs = list(
        iter_query_rewrite_records(chunks, manifest=manifest, doc_meta_lookup=meta)
    )
    assert len(pairs) == 1


# ---------------------------------------------------------------- context_answer


def test_context_answer_record_messages_format():
    chunk = _chunk(doc_id="p0", section_type="summary")
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_context_answer_record(chunk, doc_meta=meta, split="train")
    assert rec is not None
    assert rec.schema_version == SCHEMA_VERSION_SFT_CONTEXT_ANSWER
    roles = [m.role for m in rec.messages]
    assert roles == [ROLE_SYSTEM, ROLE_USER, ROLE_ASSISTANT]


def test_context_answer_user_message_has_context_and_question_markers():
    chunk = _chunk(doc_id="p0", section_type="summary")
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_context_answer_record(chunk, doc_meta=meta, split="train")
    user_content = rec.messages[1].content
    assert "[CONTEXT]" in user_content
    assert "[QUESTION]" in user_content


def test_context_answer_assistant_is_non_empty():
    chunk = _chunk(doc_id="p0", section_type="summary")
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_context_answer_record(chunk, doc_meta=meta, split="train")
    assert rec.messages[2].content.strip()


def test_context_answer_evidence_span_in_source():
    chunk = _chunk(doc_id="p0", section_type="summary")
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_context_answer_record(chunk, doc_meta=meta, split="train")
    src = rec.source.to_dict()
    assert "evidence_span" in src
    assert src["evidence_span"]


def test_context_answer_evidence_span_inside_context():
    """The literal evidence_span must appear in the [CONTEXT] block."""
    chunk = _chunk(doc_id="p0", section_type="setting")
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_context_answer_record(chunk, doc_meta=meta, split="train")
    user_content = rec.messages[1].content
    span = rec.source.evidence_span
    assert span and span in user_content
    assert span in chunk["chunk_text"]


def test_context_answer_skips_low_quality_chunk():
    """is_stub / is_table_like chunks must be skipped by default in the iterator."""
    chunk_stub = _chunk(doc_id="p0", section_type="summary", is_stub=True)
    chunk_table = _chunk(doc_id="p1", section_type="summary", is_table_like=True)
    pages = [
        _page(page_id="p0", work_id="w0", work_title="작품_0"),
        _page(page_id="p1", work_id="w1", work_title="작품_1"),
    ]
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0
    )
    meta = build_doc_meta_lookup(pages)
    pairs = list(
        iter_context_answer_records(
            [chunk_stub, chunk_table],
            manifest=manifest,
            doc_meta_lookup=meta,
        )
    )
    assert pairs == []


def test_context_answer_returns_none_for_short_chunk():
    short_chunk = _chunk(
        doc_id="p0", section_type="summary", chunk_text="짧다.", text_length=4
    )
    meta = DocMeta(work_title="작품A", page_title="작품A", aliases=[])
    rec = build_context_answer_record(
        short_chunk, doc_meta=meta, split="train", min_context_chars=60
    )
    assert rec is None


def test_is_low_quality_metadata_does_not_skip_list_like():
    """is_list_like alone should not be a low-quality signal."""
    md = {"is_list_like": True, "text_length": 200}
    low, _ = is_low_quality_metadata(md, min_chars=60)
    assert low is False


# ---------------------------------------------------------------- split leakage


def test_iterator_splits_chunks_by_manifest_doc_id():
    pages, chunks = _build_corpus(n_works=6, sections_per_work=3)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    meta = build_doc_meta_lookup(pages)

    qr_pairs = list(
        iter_query_rewrite_records(chunks, manifest=manifest, doc_meta_lookup=meta)
    )
    ca_pairs = list(
        iter_context_answer_records(chunks, manifest=manifest, doc_meta_lookup=meta)
    )

    for split, rec in qr_pairs + ca_pairs:
        # The doc_id in source must belong to the split that consumed the record
        assert rec.source.doc_id in manifest.doc_ids[split]


def test_iterator_raises_on_missing_doc_by_default():
    pages, _ = _build_corpus(n_works=2, sections_per_work=1)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0
    )
    meta = build_doc_meta_lookup(pages)
    bogus = [_chunk(doc_id="ghost", section_type="summary")]
    with pytest.raises(ValueError):
        list(
            iter_query_rewrite_records(
                bogus, manifest=manifest, doc_meta_lookup=meta
            )
        )
    with pytest.raises(ValueError):
        list(
            iter_context_answer_records(
                bogus, manifest=manifest, doc_meta_lookup=meta
            )
        )


def test_iterator_allow_missing_drops_unknown_doc():
    pages, _ = _build_corpus(n_works=2, sections_per_work=1)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0
    )
    meta = build_doc_meta_lookup(pages)
    bogus = [_chunk(doc_id="ghost", section_type="summary")]
    qr = list(
        iter_query_rewrite_records(
            bogus,
            manifest=manifest,
            doc_meta_lookup=meta,
            allow_missing_docs=True,
        )
    )
    ca = list(
        iter_context_answer_records(
            bogus,
            manifest=manifest,
            doc_meta_lookup=meta,
            allow_missing_docs=True,
        )
    )
    assert qr == [] and ca == []


# ---------------------------------------------------------------- CLI


def test_cli_writes_six_jsonl_files(tmp_path: Path):
    pages, chunks = _build_corpus(n_works=6, sections_per_work=3)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )

    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "sft"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    _write_manifest(manifest_path, manifest)

    rc = sft_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc == 0
    for kind in ("sft_query_rewrite", "sft_context_answer"):
        for s in SPLIT_NAMES:
            p = out_dir / f"{kind}.{s}.jsonl"
            assert p.exists(), f"{p} missing"


def test_cli_split_leakage_prevention(tmp_path: Path):
    pages, chunks = _build_corpus(n_works=6, sections_per_work=3)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )

    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "sft"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    _write_manifest(manifest_path, manifest)

    rc = sft_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc == 0
    for kind in ("sft_query_rewrite", "sft_context_answer"):
        for s in SPLIT_NAMES:
            for line in (
                (out_dir / f"{kind}.{s}.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
            ):
                rec = json.loads(line)
                doc_id = rec["source"]["doc_id"]
                assert doc_id in manifest.doc_ids[s], (
                    f"{kind}.{s} contains {doc_id} which belongs to a different split"
                )
                assert rec["source"]["split"] == s


def test_cli_only_query_rewrite(tmp_path: Path):
    pages, chunks = _build_corpus(n_works=4, sections_per_work=3)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "sft"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    _write_manifest(manifest_path, manifest)

    rc = sft_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
            "--only-query-rewrite",
        ]
    )
    assert rc == 0
    qr_total = sum(
        sum(1 for _ in (out_dir / f"sft_query_rewrite.{s}.jsonl").open(encoding="utf-8"))
        for s in SPLIT_NAMES
    )
    ca_total = sum(
        sum(1 for _ in (out_dir / f"sft_context_answer.{s}.jsonl").open(encoding="utf-8"))
        for s in SPLIT_NAMES
    )
    assert qr_total > 0
    assert ca_total == 0


def test_cli_only_context_answer(tmp_path: Path):
    pages, chunks = _build_corpus(n_works=4, sections_per_work=3)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "sft"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    _write_manifest(manifest_path, manifest)

    rc = sft_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
            "--only-context-answer",
        ]
    )
    assert rc == 0
    qr_total = sum(
        sum(1 for _ in (out_dir / f"sft_query_rewrite.{s}.jsonl").open(encoding="utf-8"))
        for s in SPLIT_NAMES
    )
    ca_total = sum(
        sum(1 for _ in (out_dir / f"sft_context_answer.{s}.jsonl").open(encoding="utf-8"))
        for s in SPLIT_NAMES
    )
    assert qr_total == 0
    assert ca_total > 0


def test_cli_writes_export_report(tmp_path: Path):
    pages, chunks = _build_corpus(n_works=4, sections_per_work=3)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "sft"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    _write_manifest(manifest_path, manifest)

    rc = sft_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc == 0
    rep_path = out_dir / "sft_export_report.json"
    assert rep_path.exists()
    rep = json.loads(rep_path.read_text(encoding="utf-8"))
    assert rep["schema_version"] == SCHEMA_VERSION_SFT_EXPORT_REPORT
    assert "query_rewrite" in rep["counts"]
    assert "context_answer" in rep["counts"]
    assert set(rep["skipped"].keys()) >= {
        "low_quality",
        "too_short",
        "missing_manifest",
        "missing_evidence",
        "unsupported_section_type",
    }
    assert "query_rewrite" in rep["section_type_distribution"]
    assert "context_answer" in rep["section_type_distribution"]


def test_cli_fails_on_missing_doc_by_default(tmp_path: Path):
    pages, _ = _build_corpus(n_works=2, sections_per_work=1)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0
    )
    chunks = [_chunk(doc_id="ghost", section_type="summary")]
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "sft"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    _write_manifest(manifest_path, manifest)

    rc = sft_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc != 0


def test_cli_allow_missing_docs_skips_unknown(tmp_path: Path):
    pages, real_chunks = _build_corpus(n_works=2, sections_per_work=2)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0
    )
    bogus = [_chunk(doc_id="ghost", section_type="summary", chunk_id="ghost_c0")]
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "sft"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, real_chunks + bogus)
    _write_manifest(manifest_path, manifest)

    rc = sft_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
            "--allow-missing-docs",
        ]
    )
    assert rc == 0
    rep = json.loads((out_dir / "sft_export_report.json").read_text(encoding="utf-8"))
    assert rep["skipped"]["missing_manifest"] >= 1


def test_cli_max_records_per_split_caps_output(tmp_path: Path):
    pages, chunks = _build_corpus(n_works=8, sections_per_work=3)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=0.5, valid_ratio=0.25, test_ratio=0.25
    )
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "sft"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    _write_manifest(manifest_path, manifest)

    rc = sft_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
            "--max-records-per-split", "1",
        ]
    )
    assert rc == 0
    for kind in ("sft_query_rewrite", "sft_context_answer"):
        for s in SPLIT_NAMES:
            n_lines = sum(
                1 for _ in (out_dir / f"{kind}.{s}.jsonl").open(encoding="utf-8")
            )
            assert n_lines <= 1


def test_cli_assistant_payload_round_trips_as_json(tmp_path: Path):
    pages, chunks = _build_corpus(n_works=4, sections_per_work=2)
    manifest = build_split_manifest(
        pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0
    )
    pages_path = tmp_path / "pages.jsonl"
    chunks_path = tmp_path / "chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "sft"
    _write_jsonl(pages_path, pages)
    _write_jsonl(chunks_path, chunks)
    _write_manifest(manifest_path, manifest)
    rc = sft_main(
        [
            "--pages", str(pages_path),
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc == 0
    qr_lines = (out_dir / "sft_query_rewrite.train.jsonl").read_text(encoding="utf-8").splitlines()
    assert qr_lines, "expected at least one query_rewrite record"
    for line in qr_lines:
        rec = json.loads(line)
        # last message is assistant
        payload = json.loads(rec["messages"][-1]["content"])
        assert "normalized_query" in payload
        assert "filters" in payload
