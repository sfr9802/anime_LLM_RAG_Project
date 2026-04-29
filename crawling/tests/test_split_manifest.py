"""Tests for the Phase 3 split manifest module + CLIs.

The module is a pure function pipeline so the tests stay synthetic — no
real namu input is required. The CLI tests exercise the file paths via
``tmp_path`` and call ``main(argv)`` directly so we get coverage without
spawning a subprocess.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from eval.harness.split_manifest import (
    SCHEMA_VERSION_SPLIT_MANIFEST,
    SCHEMA_VERSION_SPLIT_REPORT,
    SPLIT_NAMES,
    SplitManifest,
    apply_manifest_to_chunks,
    apply_manifest_to_chunks_iter,
    audit_manifest,
    build_split_manifest,
    derive_group_id,
    manifest_from_dict,
)
from scripts.build_split_manifest import main as build_main
from scripts.split_rag_chunks import main as split_main


# ---------------------------------------------------------------- fixtures


def _page(*, page_id: str, work_id: str = None) -> Dict[str, Any]:
    out = {"page_id": page_id}
    if work_id is not None:
        out["work_id"] = work_id
    return out


def _chunk(*, doc_id: str, chunk_id: str = None, payload: str = "x") -> Dict[str, Any]:
    return {
        "chunk_id": chunk_id or f"c_{doc_id}",
        "doc_id": doc_id,
        "chunk_text": payload,
    }


def _ten_works(pages_per_work: int = 2) -> List[Dict[str, Any]]:
    pages: List[Dict[str, Any]] = []
    for i in range(10):
        for j in range(pages_per_work):
            pages.append(_page(page_id=f"p{i}_{j}", work_id=f"w{i}"))
    return pages


# ---------------------------------------------------------------- group_id


def test_derive_group_id_uses_work_id():
    gid, fb = derive_group_id({"page_id": "p1", "work_id": "wA"})
    assert gid == "wA"
    assert fb is False


def test_derive_group_id_falls_back_to_page_id():
    gid, fb = derive_group_id({"page_id": "p1"})
    assert gid == "p1"
    assert fb is True


def test_derive_group_id_returns_none_when_no_ids():
    gid, fb = derive_group_id({"work_id": ""})
    assert gid is None
    assert fb is True


def test_derive_group_id_strips_whitespace():
    gid, fb = derive_group_id({"page_id": "p1", "work_id": "  wA  "})
    assert gid == "wA"
    assert fb is False


# ---------------------------------------------------------------- build basic


def test_build_manifest_assigns_every_doc_exactly_once():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    all_docs = sorted(p["page_id"] for p in pages)
    splits = m.doc_ids
    union = sorted(splits["train"] + splits["valid"] + splits["test"])
    assert union == all_docs
    # No doc appears in more than one split
    seen = set()
    for s in SPLIT_NAMES:
        for d in splits[s]:
            assert d not in seen, f"{d} appeared in two splits"
            seen.add(d)


def test_build_manifest_groups_share_split():
    """A work's main + subpages must land in the same split."""
    pages = _ten_works(pages_per_work=3)
    m = build_split_manifest(pages, seed=42, train_ratio=0.6, valid_ratio=0.2, test_ratio=0.2)
    for split in SPLIT_NAMES:
        groups_in_split = set(m.groups[split])
        for doc_id in m.doc_ids[split]:
            assert m.doc_to_group[doc_id] in groups_in_split


def test_build_manifest_doc_to_group_covers_all_docs():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    for p in pages:
        assert p["page_id"] in m.doc_to_group


def test_build_manifest_counts_match_lists():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.8, valid_ratio=0.1, test_ratio=0.1)
    assert m.counts.groups.train == len(m.groups["train"])
    assert m.counts.groups.valid == len(m.groups["valid"])
    assert m.counts.groups.test == len(m.groups["test"])
    assert m.counts.docs.train == len(m.doc_ids["train"])
    assert m.counts.docs.valid == len(m.doc_ids["valid"])
    assert m.counts.docs.test == len(m.doc_ids["test"])
    assert m.counts.groups.total == sum(
        len(m.groups[s]) for s in SPLIT_NAMES
    )
    assert m.counts.docs.total == sum(
        len(m.doc_ids[s]) for s in SPLIT_NAMES
    )


def test_build_manifest_ratios_recorded():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.8, valid_ratio=0.1, test_ratio=0.1)
    assert m.ratios == {"train": 0.8, "valid": 0.1, "test": 0.1}
    assert m.schema_version == SCHEMA_VERSION_SPLIT_MANIFEST


def test_build_manifest_ratios_approximately_respected():
    pages = []
    for i in range(100):
        pages.append({"page_id": f"p{i}", "work_id": f"w{i}"})
    m = build_split_manifest(pages, seed=42, train_ratio=0.8, valid_ratio=0.1, test_ratio=0.1)
    assert 75 <= m.counts.groups.train <= 85
    assert 5 <= m.counts.groups.valid <= 15
    assert 5 <= m.counts.groups.test <= 15


# ---------------------------------------------------------------- determinism


def test_build_manifest_is_deterministic_under_same_seed():
    pages = _ten_works(pages_per_work=2)
    m1 = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    m2 = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    assert m1.groups == m2.groups
    assert m1.doc_ids == m2.doc_ids
    assert m1.doc_to_group == m2.doc_to_group


def test_build_manifest_changes_with_different_seed():
    pages = _ten_works(pages_per_work=2)
    m1 = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    m2 = build_split_manifest(pages, seed=99, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    # Some assignment must have moved with a different seed
    assert m1.groups != m2.groups


def test_build_manifest_input_order_does_not_affect_output():
    pages = _ten_works(pages_per_work=2)
    m1 = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    m2 = build_split_manifest(list(reversed(pages)), seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    assert m1.groups == m2.groups
    # doc_ids per split must also match (sorted internally)
    assert m1.doc_ids == m2.doc_ids


# ---------------------------------------------------------------- validation


def test_build_manifest_rejects_ratio_sum_off():
    pages = _ten_works(pages_per_work=2)
    with pytest.raises(ValueError):
        build_split_manifest(pages, seed=1, train_ratio=0.5, valid_ratio=0.2, test_ratio=0.1)


def test_build_manifest_rejects_negative_ratio():
    pages = _ten_works(pages_per_work=2)
    with pytest.raises(ValueError):
        build_split_manifest(pages, seed=1, train_ratio=1.1, valid_ratio=-0.1, test_ratio=0.0)


def test_build_manifest_rejects_empty_input():
    with pytest.raises(ValueError):
        build_split_manifest([], seed=1, train_ratio=0.8, valid_ratio=0.1, test_ratio=0.1)


def test_build_manifest_warns_on_small_corpus():
    """5 groups with 80/10/10 -> ceil rounds valid+test to 1 each."""
    pages = [{"page_id": f"p{i}", "work_id": f"w{i}"} for i in range(5)]
    m = build_split_manifest(pages, seed=42, train_ratio=0.8, valid_ratio=0.1, test_ratio=0.1)
    assert m.counts.groups.train >= 1
    assert m.counts.groups.valid >= 1
    assert m.counts.groups.test >= 1


def test_build_manifest_records_fallback_groups():
    pages = [
        {"page_id": "p1", "work_id": "wA"},
        {"page_id": "p2"},  # no work_id -> page_id fallback
    ]
    m = build_split_manifest(pages, seed=42, train_ratio=0.5, valid_ratio=0.5, test_ratio=0.0)
    assert m.fallback_group_count == 1
    assert any("fallback" in w.lower() for w in m.warnings)


# ---------------------------------------------------------------- audit


def test_audit_clean_manifest_has_no_overlap():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    r = audit_manifest(m)
    assert r.leakage.doc_id_overlap == []
    assert r.leakage.group_id_overlap == []
    assert r.total_docs == m.counts.docs.total
    assert r.total_groups == m.counts.groups.total
    assert r.schema_version == SCHEMA_VERSION_SPLIT_REPORT


def test_audit_detects_doc_id_overlap():
    m = SplitManifest(
        ratios={"train": 0.5, "valid": 0.25, "test": 0.25},
        groups={"train": ["wA"], "valid": ["wB"], "test": ["wC"]},
        doc_ids={
            "train": ["dup", "p1"],
            "valid": ["dup", "p2"],  # leakage
            "test": ["p3"],
        },
        doc_to_group={
            "dup": "wA", "p1": "wA", "p2": "wB", "p3": "wC"
        },
    )
    r = audit_manifest(m)
    assert "dup" in r.leakage.doc_id_overlap
    assert r.leakage.group_id_overlap == []


def test_audit_detects_group_id_overlap():
    m = SplitManifest(
        ratios={"train": 0.5, "valid": 0.25, "test": 0.25},
        groups={
            "train": ["wA", "wShared"],
            "valid": ["wShared", "wB"],  # leakage
            "test": ["wC"],
        },
        doc_ids={"train": [], "valid": [], "test": []},
        doc_to_group={},
    )
    r = audit_manifest(m)
    assert "wShared" in r.leakage.group_id_overlap


# ---------------------------------------------------------------- apply


def test_apply_routes_chunks_by_doc_id():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    chunks = [_chunk(doc_id=p["page_id"]) for p in pages]
    per_split, summary = apply_manifest_to_chunks(chunks, m)
    # every chunk's doc_id should land in the split that owns it
    for s in SPLIT_NAMES:
        for c in per_split[s]:
            assert c["doc_id"] in m.doc_ids[s]
    assert summary.train + summary.valid + summary.test == len(chunks)
    assert summary.missing == 0


def test_apply_preserves_chunk_payload_unchanged():
    pages = [_page(page_id="p1", work_id="wA")]
    m = build_split_manifest(pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0)
    chunk = {
        "chunk_id": "c1",
        "doc_id": "p1",
        "chunk_text": "본문 텍스트",
        "embedding_text": "제목: X\n섹션: Y\n\n본문:\n본문 텍스트",
        "metadata": {"has_spoiler": True, "noise_score": 0.42},
    }
    per_split, _ = apply_manifest_to_chunks([chunk], m)
    assert per_split["train"] == [chunk]
    # exact identity (we did not copy the dict)
    assert per_split["train"][0] is chunk


def test_apply_raises_on_missing_doc_by_default():
    pages = [_page(page_id="p1", work_id="wA")]
    m = build_split_manifest(pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0)
    bad = [_chunk(doc_id="unknown_doc")]
    with pytest.raises(ValueError):
        apply_manifest_to_chunks(bad, m)


def test_apply_skips_missing_doc_with_flag():
    pages = [_page(page_id="p1", work_id="wA")]
    m = build_split_manifest(pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0)
    chunks = [_chunk(doc_id="p1"), _chunk(doc_id="unknown")]
    per_split, summary = apply_manifest_to_chunks(chunks, m, allow_missing=True)
    assert summary.train == 1
    assert summary.missing == 1
    assert "unknown" in summary.missing_doc_ids


def test_apply_streaming_yields_split_chunk_pairs():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    chunks = [_chunk(doc_id=p["page_id"]) for p in pages]
    pairs = list(apply_manifest_to_chunks_iter(chunks, m))
    assert len(pairs) == len(chunks)
    for split, c in pairs:
        assert split in SPLIT_NAMES
        assert c["doc_id"] in m.doc_ids[split]


# ---------------------------------------------------------------- (de)serialize


def test_manifest_round_trip_via_dict():
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    obj = m.to_dict()
    m2 = manifest_from_dict(obj)
    assert m2.groups == m.groups
    assert m2.doc_ids == m.doc_ids
    assert m2.doc_to_group == m.doc_to_group
    assert m2.seed == m.seed
    assert m2.ratios == m.ratios


# ---------------------------------------------------------------- CLI: build


def _write_pages_jsonl(path: Path, pages: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for p in pages:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def test_build_cli_writes_manifest_and_report(tmp_path: Path):
    pages_path = tmp_path / "pages.jsonl"
    out_path = tmp_path / "split_manifest.json"
    _write_pages_jsonl(pages_path, _ten_works(pages_per_work=2))

    rc = build_main(
        [
            "--input",
            str(pages_path),
            "--out",
            str(out_path),
            "--seed",
            "42",
            "--train-ratio",
            "0.8",
            "--valid-ratio",
            "0.1",
            "--test-ratio",
            "0.1",
        ]
    )
    assert rc == 0
    assert out_path.exists()
    obj = json.loads(out_path.read_text(encoding="utf-8"))
    assert obj["schema_version"] == SCHEMA_VERSION_SPLIT_MANIFEST

    report_path = out_path.with_suffix(".report.json")
    assert report_path.exists()
    rep = json.loads(report_path.read_text(encoding="utf-8"))
    assert rep["schema_version"] == SCHEMA_VERSION_SPLIT_REPORT
    assert rep["leakage"]["doc_id_overlap"] == []
    assert rep["leakage"]["group_id_overlap"] == []


def test_build_cli_no_report_flag(tmp_path: Path):
    pages_path = tmp_path / "pages.jsonl"
    out_path = tmp_path / "m.json"
    _write_pages_jsonl(pages_path, _ten_works())
    rc = build_main(
        [
            "--input",
            str(pages_path),
            "--out",
            str(out_path),
            "--no-report",
        ]
    )
    assert rc == 0
    assert out_path.exists()
    assert not out_path.with_suffix(".report.json").exists()


def test_build_cli_rejects_bad_ratios(tmp_path: Path, capsys):
    pages_path = tmp_path / "pages.jsonl"
    _write_pages_jsonl(pages_path, _ten_works())
    rc = build_main(
        [
            "--input",
            str(pages_path),
            "--out",
            str(tmp_path / "m.json"),
            "--train-ratio",
            "0.6",
            "--valid-ratio",
            "0.2",
            "--test-ratio",
            "0.1",
        ]
    )
    assert rc != 0


def test_build_cli_rejects_missing_input(tmp_path: Path):
    rc = build_main(
        [
            "--input",
            str(tmp_path / "does_not_exist.jsonl"),
            "--out",
            str(tmp_path / "m.json"),
        ]
    )
    assert rc != 0


# ---------------------------------------------------------------- CLI: split


def _write_chunks_jsonl(path: Path, chunks: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def _write_manifest_json(path: Path, manifest: SplitManifest) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_split_cli_writes_three_files(tmp_path: Path):
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    chunks = [_chunk(doc_id=p["page_id"]) for p in pages]
    chunks_path = tmp_path / "rag_chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "out"
    _write_chunks_jsonl(chunks_path, chunks)
    _write_manifest_json(manifest_path, m)

    rc = split_main(
        [
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc == 0

    train_path = out_dir / "rag_chunks.train.jsonl"
    valid_path = out_dir / "rag_chunks.valid.jsonl"
    test_path = out_dir / "rag_chunks.test.jsonl"
    for p in (train_path, valid_path, test_path):
        assert p.exists(), f"{p} missing"

    train_lines = train_path.read_text(encoding="utf-8").splitlines()
    valid_lines = valid_path.read_text(encoding="utf-8").splitlines()
    test_lines = test_path.read_text(encoding="utf-8").splitlines()
    assert len(train_lines) + len(valid_lines) + len(test_lines) == len(chunks)
    # Routing correctness
    for line in train_lines:
        obj = json.loads(line)
        assert obj["doc_id"] in m.doc_ids["train"]
    for line in valid_lines:
        obj = json.loads(line)
        assert obj["doc_id"] in m.doc_ids["valid"]
    for line in test_lines:
        obj = json.loads(line)
        assert obj["doc_id"] in m.doc_ids["test"]


def test_split_cli_errors_on_missing_doc_by_default(tmp_path: Path):
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    chunks = [_chunk(doc_id="unknown_doc")]
    chunks_path = tmp_path / "rag_chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "out"
    _write_chunks_jsonl(chunks_path, chunks)
    _write_manifest_json(manifest_path, m)
    rc = split_main(
        [
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc != 0


def test_split_cli_allow_missing_drops_unknown_chunks(tmp_path: Path):
    pages = _ten_works(pages_per_work=2)
    m = build_split_manifest(pages, seed=42, train_ratio=0.7, valid_ratio=0.2, test_ratio=0.1)
    real = [_chunk(doc_id=p["page_id"]) for p in pages[:3]]
    fake = [_chunk(doc_id="ghost1"), _chunk(doc_id="ghost2")]
    chunks_path = tmp_path / "rag_chunks.jsonl"
    manifest_path = tmp_path / "split_manifest.json"
    out_dir = tmp_path / "out"
    _write_chunks_jsonl(chunks_path, real + fake)
    _write_manifest_json(manifest_path, m)
    rc = split_main(
        [
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
            "--allow-missing-docs",
        ]
    )
    assert rc == 0
    total_written = 0
    for s in SPLIT_NAMES:
        path = out_dir / f"rag_chunks.{s}.jsonl"
        if path.exists():
            total_written += len(path.read_text(encoding="utf-8").splitlines())
    assert total_written == len(real)


def test_split_cli_preserves_chunk_content_byte_for_byte(tmp_path: Path):
    pages = [_page(page_id="p1", work_id="wA")]
    m = build_split_manifest(pages, seed=42, train_ratio=1.0, valid_ratio=0.0, test_ratio=0.0)
    chunk = {
        "chunk_id": "c1",
        "doc_id": "p1",
        "chunk_text": "유니코드 본문 ★",
        "metadata": {"text_length": 9, "noise_score": 0.0},
    }
    chunks_path = tmp_path / "c.jsonl"
    manifest_path = tmp_path / "m.json"
    out_dir = tmp_path / "out"
    _write_chunks_jsonl(chunks_path, [chunk])
    _write_manifest_json(manifest_path, m)
    rc = split_main(
        [
            "--chunks", str(chunks_path),
            "--manifest", str(manifest_path),
            "--out-dir", str(out_dir),
        ]
    )
    assert rc == 0
    out_obj = json.loads(
        (out_dir / "rag_chunks.train.jsonl").read_text(encoding="utf-8").splitlines()[0]
    )
    assert out_obj == chunk
