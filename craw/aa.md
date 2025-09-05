---
annotations_creators:
  - no-annotation
language:
  - ko
license:
  - cc-by-nc-sa-2.0
multilinguality: monolingual
size_categories:
  - 1K<n<10K
source_datasets:
  - external
task_categories:
  - question-answering
  - text-retrieval
pretty_name: NamuWiki Anime RAG
tags:
  - anime
  - namuwiki
  - korean
  - rag
  - llm
  - retrieval-augmented-generation
---

# NamuWiki Anime RAG Dataset

A Korean-language dataset of anime-related documents collected and refined from NamuWiki. Designed for **Retrieval-Augmented Generation (RAG)**, semantic search, and LLM-based QA systems.

---

## 📦 Dataset Overview

- **Total documents (raw)**: ~2.7k (varies slightly by rebuild)  
- **Format**: JSONL  
- **Language**: Korean  
- **Domain**: Japanese animation (TV series, OVAs, movies)  
- **Source**: NamuWiki (CC BY-NC-SA 2.0 KR)

> This repository ships two formats at the **repo root** (no subdirectories): the original page-level crawl (**v1**) and a processed, per-work format (**v2**) tailored for RAG.

---

## 📁 Versions (root files)

- **v1 (raw)** — page-level crawl  
  **File**: `namuwiki_anime_raw.jsonl`  
  (fields such as `title`, `url`, `parent`, `metadata.seed_title`, and either `chunks` **or** `content`)

- **v2 (processed, per-seed RAG)** — **one record per work (seed)** with normalized sections and a **character list**  
  **File**: `out_with_chars.jsonl`

**When to use which**
- Use **v2** for RAG/QA pipelines (section routing, character-aware retrieval, deduplicated chunks).  
- Use **v1** if you plan to run your own preprocessing or alternative normalization.

---

## 📄 v1 (Raw) Document Format

Each line in the raw JSONL may look like:

```json
{
  "title": "Demon Slayer",
  "url": "https://namu.wiki/w/귀멸의%20칼날",
  "parent": null,
  "metadata": {
    "seed_title": "Demon Slayer",
    "depth": 0,
    "fetched_at": "2025-08-08T11:23:11.123456"
  },
  "chunks": [
    "Demon Slayer is a Japanese anime adapted from the manga by Koyoharu Gotouge.",
    "It aired in 2019, produced by Ufotable."
  ],
  "content": "...\n(full text when chunks are absent)\n..."
}
```

---

## 🧱 v2 (Processed, Per-Seed RAG Format)

**One JSON object = one work (seed).** Sections are normalized and merged; **character pages** (where `parent ∈ {"등장인물","캐릭터","인물"}`) are aggregated into `sections.등장인물.list`.

### v2 Schema

```json
{
  "seed": "귀멸의 칼날",
  "title": "귀멸의 칼날",
  "sections": {
    "본문": {
      "text": "작품 개요...\\n\\n세계관 설명...",
      "chunks": ["작품 개요...", "세계관 설명..."],
      "urls": ["https://namu.wiki/w/귀멸의 칼날"]
    },
    "줄거리": { "text": "...", "chunks": ["..."], "urls": ["..."] },
    "설정":   { "text": "...", "chunks": ["..."], "urls": ["..."] },
    "등장인물": {
      "text": "등장인물 총론(있을 경우)",
      "chunks": ["..."],
      "urls": ["..."],
      "list": [
        { "name": "카마도 탄지로", "desc": "주인공. 물의 호흡...", "url": "https://namu.wiki/w/카마도 탄지로" },
        { "name": "카마도 네즈코", "desc": "여동생. 귀화...",      "url": "https://namu.wiki/w/카마도 네즈코" }
      ]
    }
  },
  "section_order": ["본문","줄거리","설정","등장인물"],
  "meta": { "seed_title": "귀멸의 칼날" },
  "doc_id": "9a2b1c0d4e5f6a7b8c9d01ab"
}
```

#### Normalization Rules
- Section aliases → canonical keys: `개요/시놉시스 → 줄거리`, `세계관 → 설정`, `캐릭터/인물 → 등장인물`
- `chunks` are deduplicated by content hash; `text = "\\n\\n".join(chunks)`  
- `section_order` lists only existing sections

#### Character List Construction
- From raw pages where `parent` marks a character page  
  (`등장인물`, `캐릭터`, or `인물`), grouped by `metadata.seed_title`
- `name = title`, `desc = cleaned content`, `url = page URL`
- Extremely short bios are filtered with a configurable threshold (`--min_char_desc`, default 20 chars)

---

## 🧹 Noise Filtering (per line)

Lines removed include (non-exhaustive):

- Copyright / CAPTCHA: `©`, `All Rights Reserved`, `reCAPTCHA`, `hCaptcha`
- Social/platform tails: `YouTube`, `TikTok`, `X(트위터)`, OTT/platform names
- News/press headers: `기자`, `보도자료`, `연합뉴스`, `[단독]`, `사진=`, `출처=`
- Game PR buzz: `CBT/OBT/사전등록/출시/론칭`, vendor names (e.g., `그라비티`, `넥슨`, ...)
- Relative-time headers: `3분 전`, `2시간 전`, `5일 전`  
  *(story text like `25년 전` is preserved)*
- Hashtag-only short lines, excessive Latin-only noise

---

## 📈 v2 Quick Stats

- **Records**: ~2,700 works  
- **Have `등장인물`**: ~500 works  
- **Avg characters per work**: ~7–8 (max around 10)

> Numbers can vary slightly by rebuild and filter settings.

---

## 🔧 Loading Examples

### Load v2 (processed)

```python
from datasets import load_dataset

ds = load_dataset("ArinNya/namuwiki_anime",
                  data_files="out_with_chars.jsonl",
                  split="train")

r = ds[0]
print(r["seed"], list((r["sections"] or {}).keys()))
chars = (r["sections"] or {}).get("등장인물", {}).get("list", [])
print(len(chars), chars[:3])
```

### Build a FAISS index (toy)

```python
from datasets import load_dataset
from sentence_transformers import SentenceTransformer
import faiss, numpy as np

ds = load_dataset("ArinNya/namuwiki_anime",
                  data_files="out_with_chars.jsonl",
                  split="train")

model = SentenceTransformer("snunlp/KR-SBERT-V40K-klueNLI-augSTS")
texts, metas = [], []

for ex in ds:
    seed = ex["seed"]
    sections = ex.get("sections") or {}
    # index section-level chunks
    for sec_name, sec in sections.items():
        for c in sec.get("chunks", []):
            texts.append(c)
            metas.append({"seed": seed, "section": sec_name})
    # index characters as well
    for c in (sections.get("등장인물", {}) or {}).get("list", []):
        texts.append(f"[{seed}] {c.get('name')}: {c.get('desc')}")
        metas.append({"seed": seed, "section": "등장인물", "name": c.get("name")})

emb = model.encode(texts, convert_to_numpy=True, show_progress_bar=True)
index = faiss.IndexFlatIP(emb.shape[1])
faiss.normalize_L2(emb)
index.add(emb)
```

---

## 🔎 Cleaning Criteria (v1 & v2)

**Removed**
- Advertisement-only pages, CAPTCHA blocks, evident news/press/PR headers
- Lines with only hashtags or excessive Latin-only noise

**Preserved**
- Short but relevant lines for core sections (characters/settings/plot)
- Minor tail noise replaced with empty strings when safer

---

## 💡 Use Cases

- Korean anime domain **RAG** (per-seed context + section routing)
- Character-centric QA / entity retrieval
- Dense retrieval experiments on community-edited encyclopedic text

---

## ⚠️ License

- Source: NamuWiki  
- Derived under **CC BY-NC-SA 2.0 KR**  
- **Non-commercial use only**, ShareAlike  
- License field in metadata: `cc-by-nc-sa-2.0`

---

## 🧑‍💻 Credits

- Author: [@ArinNya](https://github.com/sfr9802)  
- Blog: https://arin-nya.tistory.com/

---

## 🗓️ Why start from 2006?

*The Melancholy of Haruhi Suzumiya* (2006) significantly shaped modern character-driven anime aesthetics and light-novel culture; this dataset focuses on the contemporary “moe/bishoujo” era as a practical boundary for downstream tasks.

---

# 나무위키 애니메이션 RAG 데이터셋

한국어 위키인 **나무위키**에서 애니메이션 관련 문서를 수집하고, **RAG/QA 실험**에 적합하도록 정제했습니다.

## 📁 버전 (루트 파일)

- **v1 (raw)** — 페이지 단위 크롤 결과  
  **파일**: `namuwiki_anime_raw.jsonl`

- **v2 (processed, 작품 단위 RAG)** — **작품당 1레코드**, 표준 섹션/등장인물 리스트 포함  
  **파일**: `out_with_chars.jsonl`

## 🧱 v2 스키마

```json
{
  "seed": "작품명",
  "title": "대표 제목",
  "sections": {
    "본문": { "text": "...", "chunks": ["..."], "urls": ["..."] },
    "줄거리": { "text": "...", "chunks": ["..."], "urls": ["..."] },
    "설정":   { "text": "...", "chunks": ["..."], "urls": ["..."] },
    "등장인물": {
      "text": "...(총론)",
      "chunks": ["..."],
      "urls": ["..."],
      "list": [
        { "name": "이름", "desc": "설명", "url": "..." }
      ]
    }
  },
  "section_order": ["본문","줄거리","설정","등장인물"],
  "meta": { "seed_title": "..." },
  "doc_id": "md5(seed)[:24]"
}
```

**정규화 규칙**
- `개요/시놉시스 → 줄거리`, `세계관 → 설정`, `캐릭터/인물 → 등장인물`
- `chunks` 중복 제거 후 `text` 결합, `section_order`는 존재 섹션만 나열
- 등장인물 리스트는 `parent ∈ {등장인물, 캐릭터, 인물}`인 **개별 인물 페이지**를 `metadata.seed_title` 기준으로 묶어서 생성

**노이즈 필터 (라인 단위)**
- 저작권/리캡챠/플랫폼 꼬리, 뉴스·보도 헤더, 게임 홍보(CBT/출시 등), 상대시간 헤더(분/시간/일 전), 해시태그-only, 라틴 과다

## 📈 v2 대략 통계

- 레코드: 약 2.7k  
- `등장인물` 보유: 약 500  
- 작품당 평균 캐릭터 수: 7–8명

## 💡 활용 예시

- 작품 단위 컨텍스트 + 섹션 라우팅 기반 **RAG**
- 캐릭터 중심 QA / 엔티티 검색
- 커뮤니티 편집 백과 문서에 대한 밀집 검색 실험

## 🔎 정제 기준 (v1 & v2)

**제거**
- 광고/캡차/뉴스·보도/게임 PR 헤더
- 해시태그-only, 라틴 과다 노이즈

**보존**
- 등장인물/설정/줄거리 등 핵심 섹션 관련 짧은 문장
- 일부 꼬리 노이즈는 안전한 범위에서 치환/삭제

## ⚠️ 라이선스

- 원본: 나무위키 / **CC BY-NC-SA 2.0 KR**  
- **비상업적 사용**, 변경 시 동일 라이선스 공유  
- License: `cc-by-nc-sa-2.0`

## 🧑‍💻 제작 및 기여

- 작성자: [@ArinNya](https://github.com/sfr9802)  
- 블로그: https://arin-nya.tistory.com/

## 📅 왜 2006년부터 수집했나요?

**《스즈미야 하루히의 우울》(2006)**을 기점으로 캐릭터 중심 미학과 라이트노벨 문화가 크게 확산되었습니다. 본 데이터셋은 이 시기를 현대 “모에/미소녀” 시대의 실용적 경계로 보고 수집·정제를 진행했습니다.
