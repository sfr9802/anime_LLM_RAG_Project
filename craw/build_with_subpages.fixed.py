# -*- coding: utf-8 -*-
"""
Merge v3 dataset with raw subpages, apply noise-cleaning,
and attach both hub pages and character pages.

New options:
  --characters-into-subpages   -> put characters into subpages['등장인물'] items instead of the top-level `characters` list
  --rename-hub                  -> if a hub page with title '등장인물' exists, rename to '등장인물(허브)'
  --drop-characters-field       -> remove the `characters` field in the final output (use with --characters-into-subpages)

Usage (PowerShell):
  python .\build_with_subpages.py `
    -r .\namu_anime_raw.jsonl `
    -v .\namu_anime_v3.jsonl `
    -o .\namu_anime_v3.with_subpages.jsonl `
    --max-per-cat 50 --max-raw 8000 --max-sum 1000 `
    --characters-into-subpages --rename-hub --drop-characters-field
"""

import argparse, json, sys, re, unicodedata
from collections import defaultdict, Counter
from typing import Dict, List, Any

# ------------------------- 노이즈/정규식 -------------------------
ADS_TOKENS = [
    "무료출장","출장","24시","무이자","할부","당일발송","당일 발송","특가","견적","견적문의","문의","서비스요금",
    "A/S","AS","데이터복구","데이터 복구","전국","대표","본사","체인점찾기","홈페이지접수","온라인문의","오프라인광고","현수막",
    "고사양게이밍","하이엔드PC","파워게이밍","대덕구컴퓨터","컴닥터",
    "피부과","의원","한의원","치과","진료","예약","상담","보톡스","필러","리프팅","비만","여드름",
    "유성온천역","둔산동","유성점","지점","진료과목","클리닉"
]
NOISE_PATTERNS = [
    r"©", r"저작권.*(소유|보유)", r"All\s+Rights\s+Reserved",
    r"This site is protected by reCAPTCHA", r"hCaptcha.*(Privacy Policy|Terms)",
    r"(최근 변경|최근 토론|특수 기능)",
    r"^(YouTube|TikTok|Twitter|X|인스타그램|Facebook)\s?:?.*$",
    r"(애니플러스|라프텔|넷플릭스|디즈니\+?|티빙|왓챠|쿠팡플레이)\s?:?.*$",
    r"apply\.", r"Su zona horaria es",
    r"이\s*저작물은", r"나무위키는.*?(백과사전이\s*아니며|위키위키입니다)", r"더\s*보기", r"이전\s*역사",
]
GAME_PR_PATTERNS = [
    r"(CBT|OBT|사전\s*등록|출시|론칭|런칭|대규모\s*업데이트)\b",
    r"(그라비티|넥슨|넷마블|엔씨소프트|카카오게임즈|스마일게이트|펄어비스)\b",
    r"(라그나로크|메이플스토리|리니지|던전앤파이터|로스트아크)",
]
NEWS_HEADER_PATTERNS = [
    r"(뉴스|신문|기자|보도자료|속보|단독|취재|연합뉴스|뉴스1|스포츠서울|조선일보|한겨레|경향신문|머니투데이)\b",
    r"(사진=|영상=|출처=|자료=)\s*",
    r"\[?(단독|속보|인터뷰|오피니언|사설|칼럼)\]?",
    r"(?:日|韓|中)\s*언론|(?:일본|한국|중국)\s*언론",
]
REL_TIME_HEADER = [ r"\b\d+\s*(초|분|시간)\s*전\b" ]
POLITICS_PATTERNS = [
    r"(국정농단|특별검사|특검|선거\s*개입|대선|총선|지선|탄핵|대통령실|청와대|검찰|고발|기소|수사)\b",
    r"(김건희|윤석열|명태균|건진법사|민주당|국민의힘|한동훈|이재명)",
]

FLAGS = re.IGNORECASE
NOISE_RE    = [re.compile(p, FLAGS) for p in NOISE_PATTERNS]
GAME_PR_RE  = [re.compile(p, FLAGS) for p in GAME_PR_PATTERNS]
NEWS_RE     = [re.compile(p, FLAGS) for p in NEWS_HEADER_PATTERNS]
POLITICS_RE = [re.compile(p, FLAGS) for p in POLITICS_PATTERNS]
REL_TIME_RE = [re.compile(p, FLAGS) for p in REL_TIME_HEADER]
URL_RE   = re.compile(r"(https?://|www\.)[\w\-\uAC00-\uD7A3\.]+(?:\.[a-z]{2,}|\.kr)\b", FLAGS)
KRDOM_RE = re.compile(r"[\w\-\uAC00-\uD7A3]+(?:\.[\w\-\uAC00-\uD7A3]+)+(?:/|\b)", FLAGS)
PHONE_RE = re.compile(r"\b(?:0\d{1,2}-?\d{3,4}-?\d{4})\b")
BRAND_RE = re.compile(r"(대덕구\s*컴퓨터|오마이\s*(피[씨시]|pc))", FLAGS)
NAV_SUB_RE = re.compile(r"/\s*(작중\s*행적|논란\s*및\s*사건\s*사고|보러\s*가기|이전\s*역사)\b", FLAGS)
SPLIT_RE = re.compile(r"\n{1,}|\r+")
_WS = re.compile(r"\s+")
_ZWS = dict.fromkeys(map(ord, "\u00a0\u1680\u180e\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u200b\u200c\u200d\u202f\u205f\u2060\u3000\ufeff"), " ")

# ------------------------- 유틸 -------------------------
def clean(s: str) -> str:
    s = (s or "").translate(_ZWS)
    s = unicodedata.normalize("NFKC", s)
    return _WS.sub(" ", s).strip()

def is_noise_line(s: str) -> bool:
    if not s or len(s.strip()) < 2: return True
    txt = s.strip()
    if BRAND_RE.search(txt) or NAV_SUB_RE.search(txt): return True
    for rx in NOISE_RE + GAME_PR_RE + NEWS_RE + REL_TIME_RE + POLITICS_RE:
        if rx.search(txt): return True
    if URL_RE.search(txt) or KRDOM_RE.search(txt) or PHONE_RE.search(txt): return True
    hits = sum(1 for tok in ADS_TOKENS if tok.lower() in txt.lower())
    if hits >= 2 or ("출장" in txt and ("무료" in txt or "0원" in txt)): return True
    letters = [ch for ch in txt if ch.isalpha()]
    if letters:
        latin = sum(ch.isascii() for ch in letters)
        if latin / max(1, len(letters)) > 0.82: return True
    return False

def is_noise_block(t: str) -> bool:
    # 보조용(현재 블록 드랍은 사용 안 함)
    if not t or not t.strip(): return True
    txt = t.strip()
    if BRAND_RE.search(txt) or NAV_SUB_RE.search(txt): return True
    if URL_RE.search(txt) or KRDOM_RE.search(txt) or PHONE_RE.search(txt): return True
    for rx in NOISE_RE + NEWS_RE + POLITICS_RE + REL_TIME_RE:
        if rx.search(txt): return True
    hits = sum(1 for tok in ADS_TOKENS if tok.lower() in txt.lower())
    if hits >= 2 or ("출장" in txt and ("무료" in txt or "0원" in txt)): return True
    return False

def extract_clean_text(rec: Dict[str,Any], max_raw: int) -> str:
    """
    Merge content/chunks and strip noise line-by-line.
    IMPORTANT: do NOT drop a whole block just because it contains a marker.
    Only drop blocks if, *after* line-level filtering, nothing meaningful remains.
    """
    blocks: List[str] = []
    if isinstance(rec.get("content"), str) and rec["content"].strip():
        blocks.append(rec["content"])
    chs = rec.get("chunks")
    if isinstance(chs, list):
        for ch in chs:
            if isinstance(ch, str) and ch.strip():
                blocks.append(ch)
            elif isinstance(ch, dict):
                t = ch.get("text") or ch.get("content")
                if isinstance(t, str) and t.strip():
                    blocks.append(t)

    filtered_parts: List[str] = []
    for b in blocks:
        keep_lines: List[str] = []
        for ln in SPLIT_RE.split(b):
            ln = clean(ln)
            if not is_noise_line(ln):
                keep_lines.append(ln)
        t = " ".join(keep_lines).strip()
        if not t or len(t) < 40:
            continue
        filtered_parts.append(t)

    full = " ".join(filtered_parts).strip()
    return clean(full[:max_raw])

def summarize_text(txt: str, max_sum: int) -> str:
    return clean((txt or "")[:max_sum])

# ------------------------- 분류/판별 -------------------------
CHAR_PAT = re.compile(r"(등장인물|캐릭|성우|\(캐릭터\))", re.I)
SETTING_PAT = re.compile(r"(설정|세계관)", re.I)

def normalize_category(parent: str, title: str) -> str:
    p = (parent or "").lower()
    t = (title  or "").lower()
    if ("등장인물" in p) or ("캐릭" in p) or ("성우" in p) or ("등장인물" in t) or ("(캐릭터)" in t):
        return "등장인물"
    if ("설정" in p) or ("세계관" in p) or ("설정" in t) or ("세계관" in t):
        return "설정/세계관"
    return "기타"

def is_character_page(rec: Dict[str,Any]) -> bool:
    parent = (rec.get("parent") or "").lower()
    title  = (rec.get("title")  or "").lower()
    meta   = rec.get("metadata", {}) or {}
    depth  = meta.get("depth", 0)

    # depth 1의 '등장인물' 허브는 캐릭터 아님
    if depth == 1 and ("등장인물" in title):
        return False

    # parent 계보로 캐릭터 인식
    if ("등장인물" in parent) or ("캐릭" in parent) or ("성우" in parent):
        return True

    # depth>=2에서 타이틀/부모 보조 판정
    if depth >= 2 and rec.get("title") != meta.get("seed_title"):
        if "(캐릭터" in title or "캐릭터" in parent:
            return True
    return False

# ------------------------- IO helpers -------------------------
def read_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                yield json.loads(line)
            except Exception as e:
                sys.stderr.write(f"[WARN] JSON parse error at {path}:{i}: {e}\n")

def write_jsonl(path: str, records):
    # newline 지정 제거(Windows 개행 관련 안전)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ------------------------- 병합 로직 -------------------------
def build_raw_index(raw_path: str):
    """Group raw subpages by seed_title; skip depth==0 main page when attaching."""
    idx = defaultdict(list)
    for rec in read_jsonl(raw_path):
        meta = rec.get("metadata", {}) or {}
        seed = meta.get("seed_title") or rec.get("seed") or rec.get("title")
        if not seed:
            continue
        idx[seed].append(rec)
    return idx

def dedup_by_key(items: List[dict], key: str):
    seen = set(); out = []
    for it in items:
        k = (it.get(key) or "").strip()
        if not k or k in seen:
            continue
        seen.add(k); out.append(it)
    return out

def promote_misc_characters_into(target_bucket: List[dict], subpages: Dict[str,Any]) -> int:
    """Move '기타' entries that look like characters into target_bucket (list of subpage items)."""
    misc = subpages.get("기타") or []
    keep_misc = []
    moved = 0
    for it in misc:
        t = (it.get("title") or "")
        p = (it.get("parent") or "")
        if CHAR_PAT.search(t) or CHAR_PAT.search(p):
            target_bucket.append({
                "title": it.get("title"),
                "summary": it.get("summary"),
                "raw_text": it.get("raw_text"),
                "url": it.get("url"),
                "parent": it.get("parent"),
                "is_character": True,
            })
            moved += 1
        else:
            keep_misc.append(it)
    if moved > 0:
        if keep_misc:
            subpages["기타"] = keep_misc
        elif "기타" in subpages:
            del subpages["기타"]
    return moved

def remove_seed_duplicates(subpages: Dict[str,Any], seed: str, title: str):
    """Remove subpage items whose title equals seed/title (self-dup)."""
    removed = 0
    for cat in list(subpages.keys()):
        items = subpages.get(cat) or []
        keep = []
        for it in items:
            st = (it.get("title") or "").strip()
            if st == seed or st == title:
                removed += 1
                continue
            keep.append(it)
        if keep:
            subpages[cat] = keep
        else:
            del subpages[cat]
    return removed

def clamp_per_category(subpages: Dict[str,Any], max_per_cat: int):
    if max_per_cat <= 0:
        return 0
    trimmed = 0
    for cat, items in list(subpages.items()):
        if not isinstance(items, list):
            continue
        items_sorted = sorted(items, key=lambda x: len(x.get("raw_text") or ""), reverse=True)
        if len(items_sorted) > max_per_cat:
            trimmed += len(items_sorted) - max_per_cat
            items_sorted = items_sorted[:max_per_cat]
        subpages[cat] = items_sorted
    return trimmed

def attach_from_raw(v3_rec: dict, raw_pages: List[dict], max_per_cat: int, max_raw: int, max_sum: int,
                    chars_into_subpages: bool, rename_hub: bool, drop_characters_field: bool):
    seed = v3_rec.get("seed") or v3_rec.get("metadata", {}).get("seed_title") or v3_rec.get("title") or ""
    title= v3_rec.get("title") or ""
    subpages = v3_rec.get("subpages") or {}
    if not isinstance(subpages, dict): subpages = {}
    characters = v3_rec.get("characters")
    if not isinstance(characters, list): characters = []

    # 0) self-dup 제거
    remove_seed_duplicates(subpages, seed, title)

    # 1) (pre) rename hub in existing v3 subpages if requested
    if rename_hub and "등장인물" in subpages:
        for it in subpages["등장인물"]:
            if (it.get("title") or "").strip() == "등장인물" and not it.get("is_character"):
                it["title"] = "등장인물(허브)"

    # 2) raw 부착
    for rec in raw_pages:
        meta = rec.get("metadata", {}) or {}
        depth = meta.get("depth", 0)
        if depth == 0:
            continue

        cat = normalize_category(rec.get("parent") or "", rec.get("title") or "")
        raw_text = extract_clean_text(rec, max_raw=max_raw)
        if not raw_text:
            continue
        summary = summarize_text(raw_text, max_sum=max_sum)

        if cat == "등장인물":
            flagged = is_character_page(rec)
            # 안전장치: 부모/깊이로 다시 캐릭터 인정
            if not flagged:
                par = (rec.get("parent") or "").lower()
                if depth >= 2 and (("등장인물" in par) or ("캐릭" in par) or ("성우" in par)):
                    flagged = True

            if flagged:
                if chars_into_subpages:
                    bucket = subpages.get("등장인물") or []
                    bucket.append({
                        "title": rec.get("title"),
                        "summary": summary,
                        "raw_text": raw_text,
                        "url": rec.get("url"),
                        "parent": rec.get("parent"),
                        "is_character": True
                    })
                    subpages["등장인물"] = bucket
                else:
                    characters.append({
                        "name": rec.get("title"),
                        "summary": summary,
                        "raw_text": raw_text,
                        "url": rec.get("url"),
                        "parent": rec.get("parent"),
                        "category": "등장인물"
                    })
            else:
                bucket = subpages.get("등장인물") or []
                bucket.append({
                    "title": rec.get("title"),
                    "summary": summary,
                    "raw_text": raw_text,
                    "url": rec.get("url"),
                    "parent": rec.get("parent"),
                })
                subpages["등장인물"] = bucket
        else:
            bucket = subpages.get(cat) or []
            bucket.append({
                "title": rec.get("title"),
                "summary": summary,
                "raw_text": raw_text,
                "url": rec.get("url"),
                "parent": rec.get("parent"),
            })
            subpages[cat] = bucket

    # 3) 기존 기타->캐릭터 승격 (선택적으로 subpages에 넣음)
    if chars_into_subpages:
        bucket = subpages.get("등장인물") or []
        promote_misc_characters_into(bucket, subpages)
        if bucket:
            bucket = dedup_by_key(bucket, "title")
            seen_u = set(); dedup2 = []
            for it in bucket:
                u = (it.get("url") or "").strip()
                if u and u in seen_u:
                    continue
                if u:
                    seen_u.add(u)
                dedup2.append(it)
            subpages["등장인물"] = dedup2
        if drop_characters_field:
            if "characters" in v3_rec:
                del v3_rec["characters"]
        else:
            v3_rec["characters"] = []
    else:
        if characters:
            characters = dedup_by_key(characters, "name")
        v3_rec["characters"] = characters

    # 4) 카테고리별 de-dup (non-등장인물 포함)
    for cat in list(subpages.keys()):
        items = subpages.get(cat) or []
        items = dedup_by_key(items, "title")
        seen_u = set(); dedup2 = []
        for it in items:
            u = (it.get("url") or "").strip()
            if u and u in seen_u:
                continue
            if u:
                seen_u.add(u)
            dedup2.append(it)
        subpages[cat] = dedup2

    # 4.5) (post) rename hub for raw-attached hub too
    if rename_hub and "등장인물" in subpages:
        for it in subpages["등장인물"]:
            if (it.get("title") or "").strip() == "등장인물" and not it.get("is_character"):
                it["title"] = "등장인물(허브)"

    # 5) clamp per category
    clamp_per_category(subpages, max_per_cat)

    v3_rec["subpages"] = subpages
    return v3_rec

def main():
    ap = argparse.ArgumentParser(description="Merge raw subpages into v3 dataset with noise cleaning and character handling.")
    ap.add_argument("-r","--raw", required=True, help="raw jsonl path (contains seed_title + depth + parent)")
    ap.add_argument("-v","--v3",  required=True, help="v3 jsonl path (base dataset with LLM summaries)")
    ap.add_argument("-o","--out", required=True, help="output jsonl path")
    ap.add_argument("--max-per-cat", type=int, default=50, help="max items per subpage category (0 = no limit)")
    ap.add_argument("--max-raw", type=int, default=8000, help="max raw_text length per subpage")
    ap.add_argument("--max-sum", type=int, default=1000, help="max summary length per subpage")
    ap.add_argument("--characters-into-subpages", action="store_true", help="store character pages under subpages['등장인물'] instead of top-level characters")
    ap.add_argument("--rename-hub", action="store_true", help="rename a hub item titled '등장인물' to '등장인물(허브)'")
    ap.add_argument("--drop-characters-field", action="store_true", help="remove the `characters` field in the output (use with --characters-into-subpages)")
    args = ap.parse_args()

    raw_idx = build_raw_index(args.raw)
    out_records = []
    stats = Counter()
    for rec in read_jsonl(args.v3):
        seed = rec.get("seed") or rec.get("metadata", {}).get("seed_title") or rec.get("title") or ""
        pages = raw_idx.get(seed) or []
        before_sp = sum(len(v) for v in (rec.get("subpages") or {}).values()) if isinstance(rec.get("subpages"), dict) else 0

        new_rec = attach_from_raw(
            rec, pages, args.max_per_cat, args.max_raw, args.max_sum,
            chars_into_subpages=args.characters_into_subpages,
            rename_hub=args.rename_hub,
            drop_characters_field=args.drop_characters_field
        )

        after_sp = sum(len(v) for v in (new_rec.get("subpages") or {}).values()) if isinstance(new_rec.get("subpages"), dict) else 0
        if after_sp > before_sp: stats["docs_with_subpages"] += 1
        out_records.append(new_rec)

    write_jsonl(args.out, out_records)
    sys.stderr.write(f"[DONE] Wrote {len(out_records)} records -> {args.out}\n")
    sys.stderr.write(f"        docs_with_subpages: {stats['docs_with_subpages']}\n")

if __name__ == "__main__":
    main()
