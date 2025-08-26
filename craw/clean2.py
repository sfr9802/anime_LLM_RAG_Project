# build_from_character_pages.py
# 사용 예:
#   python build_from_character_pages.py --input D:\port\craw\crawled.jsonl --out D:\port\craw\out_with_chars.jsonl
#   python build_from_character_pages.py --input crawled.jsonl --out out_with_chars.jsonl --per-seed-dir D:\port\craw\by_seed
import argparse, os, json, re, hashlib, datetime
from collections import defaultdict, OrderedDict
from typing import List, Dict, Any, Iterable, Tuple

# ------------------------- 섹션 표준화/순서 -------------------------
SECTION_ALIASES = {
    "등장인물":"등장인물","캐릭터":"등장인물","인물":"등장인물",
    "설정":"설정","세계관":"설정",
    "줄거리":"줄거리","개요":"줄거리","시놉시스":"줄거리",
    "평가":"평가","반응":"평가",
    "에피소드":"에피소드",
    "방영":"방영","방영 정보":"방영",
}
# 요약을 맨 앞으로
SECTION_ORDER = ["요약","본문","줄거리","설정","등장인물","평가","에피소드","방영"]

# ------------------------- 노이즈 패턴 -------------------------
ADS_TOKENS = [
    "무료출장","출장","24시","무이자","할부","당일발송","당일 발송",
    "특가","견적","견적문의","문의","서비스요금","A/S","AS",
    "데이터복구","데이터 복구","전국","대표","본사","체인점찾기",
    "홈페이지접수","온라인문의","오프라인광고","현수막",
    "고사양게이밍","하이엔드PC","파워게이밍","대덕구컴퓨터","컴닥터",
    "피부과","의원","한의원","치과","진료","예약","상담",
    "보톡스","필러","리프팅","비만","여드름",
    "유성온천역","둔산동","유성점","지점"
]
NOISE_PATTERNS = [
    r"^©\s?.*$", r"저작권.*(소유|보유)", r"All\s+Rights\s+Reserved",
    r"This site is protected by reCAPTCHA.*", r"hCaptcha.*(Privacy Policy|Terms).*",
    r"^\s*최근 변경\s*$", r"^\s*최근 토론\s*$", r"^특수 기능\s*$",
    r"^(YouTube|TikTok|Twitter|X|인스타그램|Facebook)\s?:?.*$",
    r"^(애니플러스|라프텔|넷플릭스|디즈니\+?|티빙|왓챠|쿠팡플레이)\s?:?.*$",
    r"^apply\.$", r"^Su zona horaria es.*$",
    # 나무위키 고정 문구/푸터/더 보기
    r"^이 저작물은.*(?:따라 이용할 수 있습니다|Creative\s*Commons|CC[- ]BY|CC[- ]BY[- ]NC[- ]SA).*$",
    r"^나무위키는 .* (백과사전이 아니며|위키위키입니다)\.?.*$",
    r"^\s*더 보기\s*$",
    r"이 저작물은.*(?:따라 이용할 수 있습니다|Creative\s*Commons|CC[- ]BY|CC[- ]BY[- ]NC[- ]SA)",
    r"나무위키는 .* (백과사전이 아니며|위키위키입니다)",
    r"더\s*보기",
    r"이전\s*역사\s*(보러\s*가기|보기)",
]
GAME_PR_PATTERNS = [
    r"(CBT|OBT|사전\s*등록|출시|론칭|런칭|대규모\s*업데이트)\b",
    r"(그라비티|넥슨|넷마블|엔씨소프트|카카오게임즈|스마일게이트|펄어비스)\b",
    r"(라그나로크|메이플스토리|리니지|던전앤파이터|로스트아크)",
]
NEWS_HEADER_PATTERNS = [
    r"(뉴스|신문|기자|보도자료|속보|단독|취재|연합뉴스|뉴스1|스포츠서울|조선일보|한겨레|경향신문|머니투데이)\b",
    r"(사진=|영상=|출처=|자료=)\s*",
    r"^\[?(단독|속보|인터뷰|오피니언|사설|칼럼)\]?",
    r"(?:日|韓|中)\s*언론", r"(?:일본|한국|중국)\s*언론",
]
REL_TIME_HEADER = [
    r"^\s*([1-9]|1[0-9]|2[0-4])\s*시간\s*전\s*$",
    r"^\s*([1-9]|[1-5]?[0-9])\s*분\s*전\s*$",
    r"^\s*([1-7])\s*일\s*전\s*$",
    r"\b\d+\s*(초|분|시간)\s*전\b",
]
POLITICS_PATTERNS = [
    r"(국정농단|특별검사|특검|선거\s*개입|대선|총선|지선|탄핵|대통령실|청와대|검찰|고발|기소|수사)\b",
    r"(김건희|윤석열|명태균|건진법사|민주당|국민의힘|한동훈|이재명)",
]
HASHTAG = r"#\w+"

_ws = re.compile(r"\s+")
FLAGS = re.IGNORECASE
NOISE_RE    = [re.compile(p, FLAGS) for p in NOISE_PATTERNS]
GAME_PR_RE  = [re.compile(p, FLAGS) for p in GAME_PR_PATTERNS]
NEWS_RE     = [re.compile(p, FLAGS) for p in NEWS_HEADER_PATTERNS]
POLITICS_RE = [re.compile(p, FLAGS) for p in POLITICS_PATTERNS]
REL_TIME_RE = [re.compile(p, FLAGS) for p in REL_TIME_HEADER]
HASHTAG_RE  = re.compile(HASHTAG, FLAGS)

URL_RE   = re.compile(r"(https?://|www\.)[\w\-\uAC00-\uD7A3\.]+(?:\.[a-z]{2,}|\.kr)\b", FLAGS)
KRDOM_RE = re.compile(r"[\w\-\uAC00-\uD7A3]+(?:\.[\w\-\uAC00-\uD7A3]+)+(?:/|\b)", FLAGS)
PHONE_RE = re.compile(r"\b(?:0\d{1,2}-?\d{3,4}-?\d{4})\b")

SPLIT_RE = re.compile(r"\n{1,}|\r+")

def clean(s: str) -> str:
    s = (s or "").replace("\u200b"," ").replace("\ufeff"," ").strip()
    return _ws.sub(" ", s).strip()

def is_noise_line(s: str) -> bool:
    if not s or len(s.strip()) < 2: return True
    txt = s.strip()
    for rx in NOISE_RE:
        if rx.search(txt): return True
    for rx in GAME_PR_RE:
        if rx.search(txt): return True
    for rx in NEWS_RE:
        if rx.search(txt): return True
    for rx in REL_TIME_RE:
        if rx.match(txt): return True
    for rx in POLITICS_RE:
        if rx.search(txt): return True
    if URL_RE.search(txt) or KRDOM_RE.search(txt): return True
    if PHONE_RE.search(txt): return True
    hits = sum(1 for tok in ADS_TOKENS if tok.lower() in txt.lower())
    if hits >= 2: return True
    if "출장" in txt and ("무료" in txt or "0원" in txt): return True
    letters = [ch for ch in txt if ch.isalpha()]
    if letters:
        latin = sum(ch.isascii() for ch in letters)
        if latin / max(1,len(letters)) > 0.82: return True
    return False

def content_to_chunks(s: str) -> List[str]:
    out = []
    for ln in (s or "").splitlines():
        c = clean(ln)
        if not c or is_noise_line(c): continue
        out.append(c)
    return out
def is_noise_block(t: str) -> bool:
    """스티칭 이후 문단 전체에서 재검사"""
    if not t or not t.strip():
        return True
    txt = t.strip()

    # URL/도메인/전화
    if URL_RE.search(txt) or KRDOM_RE.search(txt) or PHONE_RE.search(txt):
        return True

    # 광고 키워드 다발(≥2) 또는 '출장' + ('무료' or '0원')
    hits = sum(1 for tok in ADS_TOKENS if tok.lower() in txt.lower())
    if hits >= 2 or ("출장" in txt and ("무료" in txt or "0원" in txt)):
        return True

    # 나무위키 푸터/네비/상대시각/뉴스/정치 등 어디서든 발견되면 컷
    for rx in NOISE_RE + NEWS_RE + POLITICS_RE + REL_TIME_RE:
        if rx.search(txt):
            return True

    return False

def normalize_chunk_block(block: str) -> List[str]:
    out = []
    for p in SPLIT_RE.split(block or ""):
        p = clean(p)
        if p and not is_noise_line(p):
            out.append(p)
    return out

def normalize_chunks(chunks: List[str]) -> List[str]:
    flat: List[str] = []
    for c in chunks or []:
        if "\n" in c or "\r" in c:
            flat.extend(normalize_chunk_block(c))
        else:
            t = clean(c)
            if t and not is_noise_line(t):
                flat.append(t)
    return flat

def stitch_short(chunks: List[str], min_chars: int = 80) -> List[str]:
    out, buf, cur = [], [], 0
    for c in chunks:
        if len(c) >= min_chars:
            if buf: out.append(" ".join(buf)); buf=[]; cur=0
            out.append(c)
        else:
            buf.append(c); cur += len(c) + 1
            if cur >= min_chars:
                out.append(" ".join(buf)); buf=[]; cur=0
    if buf: out.append(" ".join(buf))
    return out

def norm_section(title: str, parent: str|None) -> Tuple[str, str]:
    if parent:
        return (SECTION_ALIASES.get(parent.strip(), parent.strip()), (title or "").strip())
    return ("본문", (title or "").strip())

def stable_doc_id(seed: str) -> str:
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:24]

def iter_jsonl(paths: List[str]) -> Iterable[Dict[str, Any]]:
    for p in paths:
        if os.path.isdir(p):
            for fn in os.listdir(p):
                if fn.lower().endswith(".jsonl"):
                    yield from iter_jsonl([os.path.join(p, fn)])
        else:
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line=line.strip()
                    if not line: continue
                    try: yield json.loads(line)
                    except json.JSONDecodeError: continue

# ------------------------- LLM 요약 -------------------------
def _env(name: str, default: str) -> str:
    return os.getenv(name, default)

LLM_BASE_URL = _env("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
LLM_API_KEY  = _env("LOCAL_LLM_API_KEY", "sk-local")
LLM_MODEL    = _env("LOCAL_LLM_MODEL", "gemma-2-9b-it")
LLM_TIMEOUT  = float(_env("LOCAL_LLM_TIMEOUT", "60"))

def _llm_chat_json(prompt: str, timeout: float = None) -> Dict[str, Any]:
    # OpenAI 호환 /chat/completions 호출
    import requests
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role":"system","content":"당신은 한국어 텍스트를 간결하게 요약하는 보조자입니다. 반드시 JSON만 출력하세요."},
            {"role":"user","content": prompt}
        ],
        "temperature": 0.2,
        "top_p": 0.9,
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type":"application/json"}
    r = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=timeout or LLM_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    txt = data["choices"][0]["message"]["content"]
    # content가 JSON 문자열이어야 함. 아니면 예외
    try:
        # content 내에 코드블록 감싼 JSON이면 걷어내기
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        obj = json.loads(m.group(0) if m else txt)
        return obj
    except Exception:
        raise RuntimeError(f"LLM JSON parse error: {txt[:160]}...")

def summarize_kor(seed: str, text: str, bullets: int, max_chars: int) -> Dict[str, Any]:
    if not text: 
        return {}
    # 과도 길이 방지: 앞부분 위주로 자르되 섹션 헤더를 남기려 간단 보정
    t = text.strip()
    if len(t) > max_chars:
        t = t[:max_chars]
    prompt = (
        "다음 작품/페이지의 내용을 한국어로 간결히 요약하세요.\n"
        f"- 작품/시드: {seed}\n"
        f"- 출력 형식(JSON): {{\"summary\": \"한 문장 요약\", \"bullets\": [\"핵심 포인트 1\", ...] }}\n"
        f"- bullets 개수: {bullets}\n"
        "- 금지: 서론/결론/불필요한 감상, JSON 이외 출력, 줄임표 남발\n"
        "- 주의: 인물/설정/줄거리 핵심만. 광고/뉴스/정치 잡음 무시.\n\n"
        "본문:\n"
        f"{t}\n"
    )
    obj = _llm_chat_json(prompt)
    # 방어적 후처리
    s = (obj.get("summary") or "").strip()
    bl = [x.strip() for x in (obj.get("bullets") or []) if isinstance(x, str) and x.strip()]
    if not s and bl:
        s = bl[0]
    return {"summary": s, "bullets": bl, "model": LLM_MODEL, "ts": datetime.datetime.utcnow().isoformat() + "Z"}

# ------------------------- 메인 -------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input","-i",required=True,nargs="+",help="JSONL 파일 또는 디렉터리(복수 가능)")
    ap.add_argument("--out","-o",required=True,help="출력 JSONL 경로")
    ap.add_argument("--per-seed-dir",help="작품별 개별 파일 저장 디렉터리(선택)")
    ap.add_argument("--min_char_desc",type=int,default=20,help="등장인물 desc 최소 길이")
    ap.add_argument("--summarize", action="store_true", help="로컬 LLM으로 요약 섹션 생성")
    ap.add_argument("--sum-bullets", type=int, default=5, help="요약 bullet 개수")
    ap.add_argument("--sum-max-chars", type=int, default=16000, help="LLM 입력 최대 길이(문자)")
    args = ap.parse_args()

    out_dir = os.path.dirname(args.out)
    if out_dir and not os.path.exists(out_dir): os.makedirs(out_dir, exist_ok=True)
    if args.per_seed_dir: os.makedirs(args.per_seed_dir, exist_ok=True)

    sections_bag  = defaultdict(lambda: defaultdict(lambda: {"chunks":[], "urls":set()}))
    characters_bag= defaultdict(list)
    meta_map      = defaultdict(dict)
    title_map     = defaultdict(set)

    def add_meta(dst, src):
        for k, v in (src or {}).items():
            if v in (None, "", []): continue
            if k not in dst: dst[k] = v

    total_in=kept=0
    for r in iter_jsonl(args.input):
        total_in += 1
        url        = clean(r.get("url") or "")
        raw_section= clean(r.get("section") or r.get("parent") or r.get("category") or "")
        title      = clean(r.get("title") or "")
        meta       = r.get("metadata") or r.get("meta") or {}
        seed       = clean(meta.get("seed_title") or r.get("seed") or title)
        if not seed: 
            continue

        # 추출
        if isinstance(r.get("chunks"), list) and r["chunks"]:
            chunks = [clean(c) for c in r["chunks"] if clean(c)]
        elif isinstance(r.get("text"), str) and r["text"].strip():
            chunks = content_to_chunks(r["text"])
        elif isinstance(r.get("content"), str) and r["content"].strip():
            chunks = content_to_chunks(r["content"])
        else:
            chunks = []

        # 문단 쪼개기 + 필터 + 짧은 조각 스티칭
        chunks = stitch_short(normalize_chunks(chunks), min_chars=80)
        
        # ⬇️ 블록 재검사(핵심)
        chunks = [c for c in chunks if not is_noise_block(c)]
        section, proper_title = norm_section(title, raw_section)

        # 등장인물 개별 페이지 -> 리스트 (제목이 시드와 다르면 캐릭터명으로 간주)
        if section == "등장인물" and title and title != seed:
            desc = "\n\n".join(chunks).strip()
            if len(desc) >= args.min_char_desc:
                characters_bag[seed].append({"name": proper_title or title, "desc": desc, "url": url})
                kept += 1
            continue

        # 일반 섹션 누적
        if chunks:
            sections_bag[seed][section]["chunks"].extend(chunks)
            if url:   sections_bag[seed][section]["urls"].add(url)
            if title: title_map[seed].add(title)
            add_meta(meta_map[seed], meta)
            kept += 1

    # 쓰기
    seeds_written = 0
    with open(args.out, "w", encoding="utf-8") as out_f:
        for seed in sorted(set(list(sections_bag.keys()) + list(characters_bag.keys()))):
            secmap  = sections_bag.get(seed, {})
            ordered = [s for s in SECTION_ORDER if s in secmap] + [s for s in secmap if s not in SECTION_ORDER]
            sections= OrderedDict()

            # 일반 섹션 정제+중복 제거
            for s in ordered:
                uniq, seen = [], set()
                for t in secmap[s]["chunks"]:
                    h = hashlib.md5(t.encode("utf-8")).hexdigest()
                    if h in seen: continue
                    seen.add(h); uniq.append(t)
                if not uniq: continue
                sections[s] = {"text":"\n\n".join(uniq), "chunks": uniq, "urls": sorted(secmap[s]["urls"])}

            # 등장인물 list 삽입
            char_list = characters_bag.get(seed, [])
            if char_list:
                sec_obj = sections.get("등장인물", {"text":"", "chunks":[], "urls":[]})
                sec_obj["list"] = sorted(
                    [{"name": c["name"], "desc": c["desc"], "url": c.get("url","")} for c in char_list],
                    key=lambda x: x["name"]
                )
                sections["등장인물"] = sec_obj

            # --- 요약 생성 (옵션) ---
            if args.summarize and sections:
                try:
                    # 요약 입력: 본문/줄거리/설정/등장인물 텍스트 우선 결합
                    join_keys = ["본문","줄거리","설정","등장인물"]
                    joined = []
                    for k in join_keys:
                        v = sections.get(k)
                        if isinstance(v, dict) and v.get("text"):
                            joined.append(f"[{k}] {v['text']}")
                    if not joined:
                        # 아무 것도 없으면 모든 섹션 텍스트를 긁음
                        for k, v in sections.items():
                            if isinstance(v, dict) and v.get("text"):
                                joined.append(f"[{k}] {v['text']}")
                    full_text = "\n\n".join(joined)
                    sres = summarize_kor(seed, full_text, bullets=args.sum_bullets, max_chars=args.sum_max_chars)
                    if sres and (sres.get("summary") or sres.get("bullets")):
                        bullets_txt = "\n".join(f"- {b}" for b in (sres.get("bullets") or []))
                        ytxt = (sres.get("summary") or "").strip()
                        if bullets_txt:
                            ytxt = (ytxt + ("\n\n" if ytxt else "") + bullets_txt).strip()
                        sections["요약"] = {
                            "text": ytxt,
                            "chunks": [ytxt] if ytxt else [],
                            "urls": [],
                            "model": sres.get("model"),
                            "ts": sres.get("ts"),
                        }
                        # 요약이 앞에 오도록 정렬 재생성
                        sections = OrderedDict(
                            (k, sections[k]) for k in (["요약"] + [x for x in sections.keys() if x != "요약"])
                        )
                except Exception:
                    # 요약 실패는 조용히 무시
                    pass

            if not sections: 
                continue

            doc = {
                "seed": seed,
                "title": (sorted([t for t in title_map.get(seed, set()) if t])[:1][0] if title_map.get(seed) else seed),
                "sections": sections,
                "section_order": [s for s in SECTION_ORDER if s in sections] + [s for s in sections if s not in SECTION_ORDER],
                "meta": meta_map.get(seed, {}),
                "doc_id": stable_doc_id(seed),
            }
            out_f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            seeds_written += 1

            if args.per_seed_dir:
                safe = re.sub(r'[\\/:*?"<>|]', '_', seed)[:180] + ".jsonl"
                with open(os.path.join(args.per_seed_dir, safe), "w", encoding="utf-8") as g:
                    g.write(json.dumps(doc, ensure_ascii=False) + "\n")

    print(f"Input rows: {total_in}")
    print(f"Kept rows after noise filter: {kept}")
    print(f"Seeds written: {seeds_written}")
    print(f"Output JSONL: {args.out}")
    if args.per_seed_dir:
        print(f"Per-seed files in: {args.per_seed_dir}")

if __name__ == "__main__":
    main()
