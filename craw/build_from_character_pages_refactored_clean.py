# build_from_character_pages_refactored_clean.py
# 사용 예:
#   python build_from_character_pages_refactored_clean.py -i crawled.jsonl -o out_with_chars.jsonl --summarize --sum-bullets 5 --top-summary --to-mongo --to-chroma --embed-device cpu

from __future__ import annotations
import argparse
import os
import json
import re
import hashlib
import unicodedata
import logging
from collections import defaultdict
from typing import List, Dict, Any, Iterable, Tuple
from datetime import datetime, timezone

# ------------------------- 로깅 -------------------------
LOG = logging.getLogger("builder")

def setup_logging(debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

# ------------------------- ENV (Mongo / Vector) -------------------------
# --- Mongo ---
MONGO_URI       = os.getenv("MONGO_URI", "mongodb://raguser:ragpass@localhost:27017/clean_namu_crawl?authSource=clean_namu_crawl")
MONGO_DB        = os.getenv("MONGO_DB", "clean_namu_crawl")
MONGO_RAW_COL   = os.getenv("MONGO_RAW_COL", "pages")
MONGO_CHUNK_COL = os.getenv("MONGO_CHUNK_COL", "chunks")
# --- Vector / Embedding ---
CHROMA_PATH       = os.getenv("CHROMA_PATH", "./data/chroma")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION", "namu-anime")
EMBED_MODEL       = os.getenv("EMBED_MODEL", "BAAI/bge-m3")
EMBED_BATCH       = int(os.getenv("EMBED_BATCH", "32"))
VECTOR_BACKEND    = os.getenv("VECTOR_BACKEND", "chroma").lower()

# ------------------------- 섹션 표준화/순서 -------------------------
SECTION_ALIASES = {
    "등장인물":"등장인물","캐릭터":"등장인물","인물":"등장인물",
    "설정":"설정","세계관":"설정",
    "줄거리":"줄거리","개요":"줄거리","시놉시스":"줄거리",
    "평가":"평가","반응":"평가",
    "에피소드":"에피소드",
    "방영":"방영","방영 정보":"방영",
}
SECTION_ORDER = ["요약","본문","줄거리","설정","등장인물","평가","에피소드","방영"]

# ------------------------- 노이즈 패턴 -------------------------
ADS_TOKENS = [
    "무료출장","출장","24시","무이자","할부","당일발송","당일 발송","특가","견적","견적문의","문의","서비스요금",
    "A/S","AS","데이터복구","데이터 복구","전국","대표","본사","체인점찾기","홈페이지접수","온라인문의","오프라인광고","현수막",
    # 상업 키워드 보강
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
    # 나무위키 푸터/네비
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
    if not s or len(s.strip()) < 2:
        return True
    txt = s.strip()
    if BRAND_RE.search(txt) or NAV_SUB_RE.search(txt):
        return True
    for rx in NOISE_RE + GAME_PR_RE + NEWS_RE + REL_TIME_RE + POLITICS_RE:
        if rx.search(txt):
            return True
    if URL_RE.search(txt) or KRDOM_RE.search(txt) or PHONE_RE.search(txt):
        return True
    hits = sum(1 for tok in ADS_TOKENS if tok.lower() in txt.lower())
    if hits >= 2 or ("출장" in txt and ("무료" in txt or "0원" in txt)):
        return True
    letters = [ch for ch in txt if ch.isalpha()]
    if letters:
        latin = sum(ch.isascii() for ch in letters)
        if latin / max(1, len(letters)) > 0.82:
            return True
    return False

def is_noise_block(t: str) -> bool:
    if not t or not t.strip():
        return True
    txt = t.strip()
    if BRAND_RE.search(txt) or NAV_SUB_RE.search(txt):
        return True
    if URL_RE.search(txt) or KRDOM_RE.search(txt) or PHONE_RE.search(txt):
        return True
    for rx in NOISE_RE + NEWS_RE + POLITICS_RE + REL_TIME_RE:
        if rx.search(txt):
            return True
    hits = sum(1 for tok in ADS_TOKENS if tok.lower() in txt.lower())
    if hits >= 2 or ("출장" in txt and ("무료" in txt or "0원" in txt)):
        return True
    return False

def content_to_chunks(s: str) -> List[str]:
    out = []
    for ln in (s or "").splitlines():
        c = clean(ln)
        if c and not is_noise_line(c):
            out.append(c)
    return out

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
            if buf:
                out.append(" ".join(buf)); buf=[]; cur=0
            out.append(c)
        else:
            buf.append(c); cur += len(c) + 1
            if cur >= min_chars:
                out.append(" ".join(buf)); buf=[]; cur=0
    if buf:
        out.append(" ".join(buf))
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
                    if not line:
                        continue
                    try:
                        yield json.loads(line)
                    except json.JSONDecodeError:
                        LOG.warning("JSON decode 실패: %s", line[:120])
                        continue

# ------------------------- 섹션 헤더 감지 & 본문 복원 -------------------------
HEAD_MAP = {
    "등장인물": ["등장 ?인물","캐릭터","인물 ?소개","주요 ?등장인물","등장 ?캐릭터","캐릭터 소개","등장 인물","인물","성우","등장인물 및 성우"],
    "설정": ["설정","세계관"],
    "줄거리": ["줄거리","개요","시놉시스"],
    "평가": ["평가","반응"],
    "에피소드": ["에피소드"],
    "방영": ["방영","방영 정보"],
}
HEAD_RE = {sec: re.compile(rf"^(?:=+)?\s*(?:{'|'.join(pats)})\s*(?:=+)?$", re.IGNORECASE)
           for sec, pats in HEAD_MAP.items()}

def recover_sections_from_body(sections: dict) -> dict:
    body = sections.get("본문")
    if not isinstance(body, dict):
        return sections
    lines = list(body.get("chunks") or [])
    if not lines:
        return sections

    current = None
    buckets = {sec: [] for sec in HEAD_MAP}
    rest = []
    for ln in lines:
        hit = None
        for sec, rx in HEAD_RE.items():
            if rx.match(ln):
                hit = sec; break
        if hit:
            current = hit; continue
        if current:
            buckets[current].append(ln)
        else:
            rest.append(ln)

    sections["본문"]["chunks"] = rest
    sections["본문"]["text"] = "\n\n".join(rest)

    for sec, lst in buckets.items():
        if lst and sec not in sections:
            sections[sec] = {"text":"\n\n".join(lst), "chunks": lst, "urls":[]}
    return sections

# ------------------------- 등장인물 리스트 오탐 컷 -------------------------
NON_CHAR_NAMES = {"설정","평가","음악","방영","줄거리","에피소드","개요","세계관","명대사"}

def looks_non_character(name: str) -> bool:
    if not name:
        return True
    if "/" in name:
        return True
    base = name.strip().lower()
    if base in {s.lower() for s in NON_CHAR_NAMES}:
        return True
    if any(k in name for k in NON_CHAR_NAMES):
        return True
    return False

# ------------------------- LLM 요약 -------------------------

def _env(name: str, default: str) -> str:
    return os.getenv(name, default)

LLM_BASE_URL = _env("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
LLM_API_KEY  = _env("LOCAL_LLM_API_KEY", "sk-local")
LLM_MODEL    = _env("LOCAL_LLM_MODEL", "gemma-2-9b-it")
LLM_TIMEOUT  = float(_env("LOCAL_LLM_TIMEOUT", "60"))
MAX_JSON_RETRIES_DEFAULT = int(_env("LOCAL_LLM_JSON_RETRIES", "1"))
FAIL_LOG_DIR_DEFAULT = _env("LOCAL_LLM_FAIL_LOG_DIR", "")

SMART = str.maketrans({
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‘": "'",  "’": "'",  "‚": "'",  "‛": "'",
})
FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE | re.MULTILINE)

def _strip_code_fence(s: str) -> str:
    return FENCE_RE.sub("", s)

# 안전: 문자열 바깥의 주석만 제거
def _strip_js_comments_outside_strings(s: str) -> str:
    out=[]; i=0; n=len(s); in_str=False; esc=False
    while i<n:
        ch=s[i]
        if in_str:
            out.append(ch)
            if esc: esc=False
            elif ch == '\\': esc=True
            elif ch == '"': in_str=False
            i+=1
        else:
            if ch == '"':
                in_str=True; out.append(ch); i+=1
            elif ch == '/' and i+1<n and s[i+1] == '/':
                i+=2
                while i<n and s[i] not in '\r\n': i+=1
            elif ch == '/' and i+1<n and s[i+1] == '*':
                i+=2
                while i+1<n and not (s[i] == '*' and s[i+1] == '/'): i+=1
                i += 2 if i+1<n else 1
            else:
                out.append(ch); i+=1
    return ''.join(out)

# 안전: 문자열 바깥의 트레일링 콤마만 제거
def _remove_trailing_commas_outside_strings(s: str) -> str:
    out=[]; i=0; n=len(s); in_str=False; esc=False
    while i<n:
        ch=s[i]
        if in_str:
            out.append(ch)
            if esc: esc=False
            elif ch=='\\': esc=True
            elif ch=='"': in_str=False
            i+=1
        else:
            if ch=='"':
                in_str=True; out.append(ch); i+=1
            elif ch==',':
                j=i+1
                while j<n and s[j] in ' \t\r\n': j+=1
                if j<n and s[j] in '}]':
                    i+=1
                    continue
                out.append(ch); i+=1
            else:
                out.append(ch); i+=1
    return ''.join(out)

def _extract_candidate_jsons(s: str) -> List[str]:
    out: List[str] = []
    i = 0; n = len(s)
    while i < n:
        if s[i] != '{':
            i += 1; continue
        start = i
        depth = 0; in_str = False; esc = False
        while i < n:
            ch = s[i]
            if in_str:
                if esc: esc = False
                elif ch == "\\": esc = True
                elif ch == '"': in_str = False
            else:
                if ch == '"': in_str = True
                elif ch == '{': depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        out.append(s[start:i+1]); i += 1; break
            i += 1
        else:
            break
    return out

def _escape_newlines_inside_strings(s: str) -> str:
    out = []
    in_str = False; esc = False
    for ch in s:
        if in_str:
            if esc:
                out.append(ch); esc = False
            else:
                if ch == "\\": out.append(ch); esc = True
                elif ch == '"': out.append(ch); in_str = False
                elif ch == "\n": out.append("\\n")
                elif ch == "\r": out.append("\\r")
                else: out.append(ch)
        else:
            if ch == '"': in_str = True
            out.append(ch)
    return "".join(out)

def _coerce_json_like(blob: str) -> Dict[str, Any]:
    raw = _strip_code_fence(blob)

    # 0) Fast path: 이미 순정 JSON이면 그대로
    try:
        return json.loads(raw)
    except Exception:
        pass

    # 1) 스마트 따옴표 정규화
    s = raw.translate(SMART)

    # 2) 문자열 바깥 주석 제거
    s = _strip_js_comments_outside_strings(s)
    try:
        return json.loads(s)
    except Exception:
        pass

    # 3) 문자열 바깥 트레일링 콤마 제거
    s = _remove_trailing_commas_outside_strings(s)
    try:
        return json.loads(s)
    except Exception:
        pass

    # 4) 키 따옴표 누락만 보정 (값 문자열 건드리지 않음)
    s2 = re.sub(r'(?P<pre>[{,]\s*)(?P<key>[A-Za-z0-9_]+)\s*:', r'\g<pre>"\g<key>":', s)
    if s2 != s:
        try:
            return json.loads(s2)
        except Exception:
            s = s2

    # 5) 후보 JSON 블록 추출 시도
    for blk in _extract_candidate_jsons(s):
        try:
            return json.loads(blk)
        except Exception:
            continue

    # 6) 마지막 구제: summary/bullets만 긁기
    m_sum = re.search(r'"summary"\s*:\s*"((?:[^"\\]|\\.)*)"', s, re.S)
    m_arr = re.search(r'"bullets"\s*:\s*\[(.*?)\]', s, re.S)
    bullets = []
    if m_arr:
        bullets = re.findall(r'"((?:[^"\\]|\\.)*)"', m_arr.group(1), re.S)
    salv = {"summary": (m_sum.group(1) if m_sum else "").strip(), "bullets": [b.strip() for b in bullets]}
    if salv.get("summary") or salv.get("bullets"):
        return salv
    raise RuntimeError("LLM JSON parse error")

def _llm_chat_json(prompt: str, timeout: float | None = None, retries: int = MAX_JSON_RETRIES_DEFAULT, fail_log_dir: str = FAIL_LOG_DIR_DEFAULT) -> Dict[str, Any]:
    import requests
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system",
             "content": ('오직 RFC8259 JSON 객체만 출력: {"summary":"…","bullets":["…"]}. 기타 텍스트 금지. 줄바꿈은 문자열 내에서 \\n')},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.0,
        "top_p": 0.9,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type":"application/json"}
    attempts = 0
    last_raw = ""
    while True:
        attempts += 1
        try:
            try:
                r = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=timeout or LLM_TIMEOUT)
                r.raise_for_status()
                data = r.json()
            except Exception:
                payload.pop("response_format", None)
                r = requests.post(f"{LLM_BASE_URL}/chat/completions", headers=headers, json=payload, timeout=timeout or LLM_TIMEOUT)
                r.raise_for_status()
                data = r.json()
            txt = data["choices"][0]["message"]["content"]
            last_raw = txt
            return _coerce_json_like(txt)
        except Exception as e:
            LOG.error("LLM JSON parse fail: %s ...", (last_raw or "")[:800])
            if attempts > max(0, retries):
                if fail_log_dir:
                    try:
                        os.makedirs(fail_log_dir, exist_ok=True)
                        ts = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
                        path = os.path.join(fail_log_dir, f"json_fail_{ts}.txt")
                        with open(path, "w", encoding="utf-8") as fp:
                            fp.write(last_raw)
                        LOG.error("saved failed raw to %s", path)
                    except Exception:
                        pass
                raise RuntimeError("LLM JSON parse error") from e
            payload["messages"][0]["content"] = '오직 JSON 객체만: {"summary":"…","bullets":["…"]}'
            payload["messages"][1]["content"] = "정답(JSON)만 출력. 기타 금지.\n" + payload["messages"][1]["content"]

def summarize_kor(seed_title: str, text: str, bullets: int, max_chars: int,
                  json_retries: int = MAX_JSON_RETRIES_DEFAULT,
                  fail_log_dir: str = FAIL_LOG_DIR_DEFAULT) -> Dict[str, Any]:
    if not text:
        return {}
    t = text.strip()
    if len(t) > max_chars:
        t = t[:max_chars]
    prompt = (
        "다음 텍스트를 한국어로 요약.\n"
        f"- 작품/시드: {seed_title}\n"
        '- 출력: {"summary":"한 문장", "bullets": ["핵심", ...]}\n'
        f"- bullets 최대 {bullets}개, 각 80자 이내. 줄바꿈 금지.\n"
        "- 광고/뉴스/정치 잡음 무시.\n\n"
        f"{t}\n"
    )
    obj = _llm_chat_json(prompt, retries=json_retries, fail_log_dir=fail_log_dir)
    s  = (obj.get("summary") or "").strip()
    bl = [x.strip() for x in (obj.get("bullets") or []) if isinstance(x, str) and x.strip()]
    if not s and bl:
        s = bl[0]
    return {"summary": s, "bullets": bl, "model": LLM_MODEL, "ts": datetime.now(timezone.utc).isoformat()}

# ------------------------- Vector/Mongo sinks -------------------------
class STEmbedder:
    def __init__(self, model_name: str = EMBED_MODEL, device: str = "cpu", batch_size: int = EMBED_BATCH):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name, device=device)
        self.batch_size = batch_size
    def encode(self, texts: List[str]) -> List[List[float]]:
        import numpy as np
        if not texts: return []
        arr = self.model.encode(
            texts,
            batch_size=self.batch_size,
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False
        )
        return [v.astype(np.float32).tolist() for v in arr]

class MongoSink:
    def __init__(self):
        from pymongo import MongoClient, ASCENDING
        self._ASC = ASCENDING
        self.cli = MongoClient(MONGO_URI)
        db = self.cli[MONGO_DB]
        self.pages = db[MONGO_RAW_COL]
        self.chunks = db[MONGO_CHUNK_COL]
        self.ensure_indexes()

    def _ensure_index(self, coll, keys, name: str, **options):
        """기존 인덱스 옵션 불일치 시 드롭하고 재생성."""
        try:
            idxs = list(coll.list_indexes())
            for ix in idxs:
                if tuple(ix.get("key", {}).items()) == tuple(keys) and ix.get("name") == name:
                    LOG.info("index exists on %s: %s (name=%s) — skip create", coll.name, tuple(keys), name)
                    return
                if tuple(ix.get("key", {}).items()) == tuple(keys) and ix.get("name") != name:
                    LOG.warning("dropping existing index %s on %s due to name mismatch -> %s", ix.get("name"), coll.name, name)
                    coll.drop_index(ix.get("name"))
            coll.create_index(keys, name=name, **options)
            LOG.info("created index on %s: %s (name=%s, opts=%s)", coll.name, tuple(keys), name, options)
        except Exception as e:
            LOG.error("ensure_index failed on %s: %s", coll.name, e)
            raise

    def ensure_indexes(self):
        # pages: _id는 기본 unique. 보조 인덱스들
        self._ensure_index(self.pages, [("doc_id", 1)], "idx_doc_id")
        self._ensure_index(self.pages, [("seed", 1)],   "idx_seed")
        self._ensure_index(self.pages, [("title", 1)],  "idx_title")
        self._ensure_index(self.pages, [("created_at", 1)], "idx_created_at")
        self._ensure_index(self.pages, [("vectorized", 1)], "idx_vectorized")

        # chunks: doc_id+seg_index 고유키
        self._ensure_index(self.chunks, [("doc_id", 1), ("seg_index", 1)], "u_doc_seg", unique=True)
        self._ensure_index(self.chunks, [("section", 1)], "idx_section")

    def upsert_page(self, doc: Dict[str, Any], n_segments: int, all_urls: List[str]):
        y = (doc.get("sections") or {}).get("요약") or {}
        page = {
            "_id": doc["doc_id"],
            "doc_id": doc["doc_id"],
            "seed": doc.get("seed"),
            "title": doc.get("title"),
            "urls": all_urls,
            "sections": doc.get("sections"),   # 섹션 전체(원문 + 섹션별 summary 포함)
            "summary": doc.get("summary"),
            "sum_bullets": doc.get("sum_bullets", []),
            "summary_model": y.get("model"),
            "summary_ts": y.get("ts"),
            "meta": doc.get("meta") or {},
            "created_at": doc.get("created_at"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "n_segments": int(n_segments),
            "vectorized": False,
            "vector_ts": None,
            "chroma_segment_ids": [],
        }
        self.pages.replace_one({"_id": page["_id"]}, page, upsert=True)

    def upsert_chunks(self, doc: Dict[str, Any]) -> Tuple[List[str], List[str], List[Dict[str, Any]]]:
        # 재실행 시 중복키 방지: 해당 doc_id의 기존 청크 전부 제거 후 재삽입
        self.chunks.delete_many({"doc_id": doc["doc_id"]})

        ids, texts, metas = [], [], []
        idx = 0
        for sec_name, sec_obj in (doc.get("sections") or {}).items():
            if sec_name == "요약":  # 요약은 색인 제외(선택)
                continue
            if not isinstance(sec_obj, dict):
                continue
            for c in (sec_obj.get("chunks") or []):
                cid = f"{doc['doc_id']}:{idx}"
                chunk_doc = {
                    "_id": cid,
                    "doc_id": doc["doc_id"],
                    "seg_index": idx,
                    "section": sec_name,
                    "title": doc.get("title"),
                    "urls": sec_obj.get("urls") or [],
                    "text": c,
                    "created_at": doc.get("created_at"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                self.chunks.replace_one({"_id": cid}, chunk_doc, upsert=True)
                ids.append(cid); texts.append(c)
                metas.append({"doc_id": doc["doc_id"], "seg_index": idx, "section": sec_name, "title": doc.get("title")})
                idx += 1
        return ids, texts, metas

    def mark_vectorized(self, doc_id: str, seg_ids: List[str]):
        self.pages.update_one(
            {"_id": doc_id},
            {"$set": {"vectorized": True, "vector_ts": datetime.now(timezone.utc).isoformat(), "chroma_segment_ids": seg_ids}}
        )

    def close(self):
        try: self.cli.close()
        except: pass

class ChromaSink:
    def __init__(self, embedder: STEmbedder):
        if VECTOR_BACKEND != "chroma":
            raise RuntimeError(f"Unsupported VECTOR_BACKEND={VECTOR_BACKEND}")
        import chromadb
        self.client = chromadb.PersistentClient(path=CHROMA_PATH)
        try:
            self.coll = self.client.get_collection(CHROMA_COLLECTION)
        except:
            self.coll = self.client.create_collection(CHROMA_COLLECTION, metadata={"embed_model": EMBED_MODEL})
        self.embedder = embedder
    def upsert_embeddings(self, ids: List[str], texts: List[str], metas: List[Dict[str, Any]]) -> List[str]:
        if not ids: return []
        vectors = self.embedder.encode(texts)  # CPU/지정 디바이스
        self.coll.upsert(ids=ids, documents=texts, metadatas=metas, embeddings=vectors)
        return ids

# ------------------------- 보조: 평탄화/URL 수집 -------------------------
def flatten_segments_from_sections(sections: Dict[str, Any]) -> List[str]:
    segs: List[str] = []
    order = [s for s in SECTION_ORDER if s in sections] + [s for s in sections if s not in SECTION_ORDER]
    for s in order:
        if s == "요약": continue
        v = sections.get(s)
        if isinstance(v, dict):
            for c in v.get("chunks") or []:
                if c: segs.append(c)
    return segs

def collect_all_urls(sections: Dict[str, Any]) -> List[str]:
    urls = []
    for v in sections.values():
        if isinstance(v, dict):
            u = v.get("urls") or []
            if u: urls.extend(u)
    seen = set(); out=[]
    for u in urls:
        if u in seen: continue
        seen.add(u); out.append(u)
    return out

# ------------------------- 메인 -------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input","-i",required=True,nargs="+",help="JSONL 파일 또는 디렉터리(복수 가능)")
    ap.add_argument("--out","-o",required=True,help="출력 JSONL 경로")
    ap.add_argument("--per-seed-dir",help="작품별 개별 파일 저장 디렉터리(선택)")
    ap.add_argument("--min_char_desc",type=int,default=20,help="등장인물 desc 최소 길이")
    ap.add_argument("--summarize", action="store_true", help="로컬 LLM으로 요약 섹션 생성 (+섹션별 summary)")
    ap.add_argument("--sum-bullets", type=int, default=5, help="요약 bullet 개수")
    ap.add_argument("--sum-max-chars", type=int, default=16000, help="LLM 입력 최대 길이(문자)")
    ap.add_argument("--debug", action="store_true", help="디버그 로그 출력")
    ap.add_argument("--top-summary", action="store_true", help="요약을 최상위 필드(summary/sum_bullets)로도 기록")
    # 섹션별 요약 on/off
    ap.add_argument("--sum-per-section", dest="sum_per_section", action="store_true")
    ap.add_argument("--no-sum-per-section", dest="sum_per_section", action="store_false")
    ap.set_defaults(sum_per_section=True)
    # 보일러 컷 옵션
    ap.add_argument("--boiler-seed-thresh", type=int, default=0, help="서로 다른 seed에서 이 횟수 이상 나오면 보일러로 간주(0=비활성)")
    ap.add_argument("--boiler-len-max", type=int, default=80, help="보일러 후보의 최대 길이")
    ap.add_argument("--json-retries", type=int, default=MAX_JSON_RETRIES_DEFAULT, help="JSON 파싱 실패 시 재시도 횟수")
    ap.add_argument("--json-fail-log-dir", type=str, default=FAIL_LOG_DIR_DEFAULT, help="실패한 원문을 저장할 디렉터리(공백=비활성)")
    # 인덱싱 옵션
    ap.add_argument("--to-mongo", action="store_true", help="Mongo pages/chunks 업서트")
    ap.add_argument("--to-chroma", action="store_true", help="Chroma 임베딩 업서트")
    ap.add_argument("--embed-device", type=str, default="cpu", choices=["cpu","cuda"], help="임베딩 디바이스")
    args = ap.parse_args()
    setup_logging(args.debug)

    out_dir = os.path.dirname(args.out)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)
    if args.per_seed_dir:
        os.makedirs(args.per_seed_dir, exist_ok=True)

    # 싱크 준비
    mongo = MongoSink() if args.to_mongo else None
    embedder = STEmbedder(device=args.embed_device) if args.to_chroma else None
    chroma = ChromaSink(embedder) if args.to_chroma else None

    sections_bag  = defaultdict(lambda: defaultdict(lambda: {"chunks":[], "urls":set()}))
    characters_bag= defaultdict(list)
    meta_map      = defaultdict(dict)
    title_map     = defaultdict(set)
    line_seed     = defaultdict(set)   # 보일러 감지용: 문장 -> seed 집합

    def add_meta(dst, src):
        for k, v in (src or {}).items():
            if v in (None, "", []):
                continue
            if k not in dst:
                dst[k] = v

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

        # 문단 분해 + 라인 필터 + 스티칭 + 블록 재검사
        chunks = stitch_short(normalize_chunks(chunks), min_chars=80)
        chunks = [c for c in chunks if not is_noise_block(c)]

        section, proper_title = norm_section(title, raw_section)

        # 보일러 후보 기록
        thr = args.boiler_seed_thresh
        if thr:
            for c in chunks:
                if c and len(c) <= args.boiler_len_max:
                    line_seed[c].add(seed)

        # 등장인물 개별 페이지 -> 리스트
        if section == "등장인물" and title and title != seed:
            if looks_non_character(proper_title or title):
                continue
            desc = "\n\n".join(chunks).strip()
            if len(desc) >= args.min_char_desc:
                characters_bag[seed].append({"name": proper_title or title, "desc": desc, "url": url})
                kept += 1
            continue

        # 일반 섹션 누적
        if chunks:
            sections_bag[seed][section]["chunks"].extend(chunks)
            if url:
                sections_bag[seed][section]["urls"].add(url)
            if title:
                title_map[seed].add(title)
            add_meta(meta_map[seed], meta)
            kept += 1

    # --- 보일러 집합 생성 ---
    boiler = set()
    if args.boiler_seed_thresh and line_seed:
        boiler = {
            line for line, seeds in line_seed.items()
            if len(seeds) >= args.boiler_seed_thresh and len(line) <= args.boiler_len_max
        }
        LOG.info("[boiler] candidates: %d (thresh=%d, len<=%d)", len(boiler), args.boiler_seed_thresh, args.boiler_len_max)

    # 쓰기
    seeds_written = 0
    seeds_with_summary = 0
    with open(args.out, "w", encoding="utf-8") as out_f:
        for seed in sorted(set(list(sections_bag.keys()) + list(characters_bag.keys()))):
            secmap  = sections_bag.get(seed, {})
            ordered = [s for s in SECTION_ORDER if s in secmap] + [s for s in secmap if s not in SECTION_ORDER]
            sections: Dict[str, Any] = {}

            # 일반 섹션 정제+중복 제거(+보일러 컷)
            for s in ordered:
                uniq, seen = [], set()
                for t in secmap[s]["chunks"]:
                    if boiler and t in boiler:
                        continue
                    h = hashlib.md5(t.encode("utf-8")).hexdigest()
                    if h in seen:
                        continue
                    seen.add(h); uniq.append(t)
                if not uniq:
                    continue
                sections[s] = {"text":"\n\n".join(uniq), "chunks": uniq, "urls": sorted(secmap[s]["urls"])}

            # 본문에서 섹션 복원
            sections = recover_sections_from_body(sections)

            # 등장인물 list 삽입
            char_list = characters_bag.get(seed, [])
            if char_list:
                sec_obj = sections.get("등장인물", {"text":"", "chunks":[], "urls":[]})
                seen_names = set()
                merged = []
                for c in sorted(char_list, key=lambda x: x["name"]):
                    if c["name"] in seen_names:
                        continue
                    seen_names.add(c["name"]); merged.append(c)
                sec_obj["list"] = [{"name": c["name"], "desc": c["desc"], "url": c.get("url","")}
                                     for c in merged]
                sections["등장인물"] = sec_obj

            # (옵션) 섹션별 요약 추가
            if args.summarize and args.sum_per_section:
                for s, obj in list(sections.items()):
                    if s == "요약":
                        continue
                    if isinstance(obj, dict) and obj.get("text"):
                        try:
                            sres_sec = summarize_kor(
                                seed_title=f"{seed} / {s}",
                                text=obj["text"],
                                bullets=min(3, args.sum_bullets),
                                max_chars=min(args.sum_max_chars, 3000),
                                json_retries=args.json_retries,
                                fail_log_dir=args.json_fail_log_dir,
                            )
                            if sres_sec and (sres_sec.get("summary")):
                                obj["summary"] = sres_sec["summary"][:280].strip()
                        except Exception as e:
                            LOG.warning("[section-summary] 실패 seed=%s sec=%s: %s", seed, s, e)

            # 문서 전체 요약 (옵션)
            if args.summarize and sections:
                try:
                    join_keys = ["본문","줄거리","설정","등장인물"]
                    joined = []
                    for k in join_keys:
                        v = sections.get(k)
                        if isinstance(v, dict) and v.get("text"):
                            joined.append(f"[{k}] {v['text']}")
                    if not joined:
                        for k, v in sections.items():
                            if isinstance(v, dict) and v.get("text"):
                                joined.append(f"[{k}] {v['text']}")
                    full_text = "\n\n".join(joined)
                    sres = summarize_kor(
                        seed_title=seed,
                        text=full_text if full_text.strip() else "",
                        bullets=args.sum_bullets,
                        max_chars=args.sum_max_chars,
                        json_retries=args.json_retries,
                        fail_log_dir=args.json_fail_log_dir,
                    ) if full_text.strip() else {}
                    if sres and (sres.get("summary") or sres.get("bullets")):
                        ytxt = (sres.get("summary") or "").strip()[:280]
                        ybul = [b.strip()[:120] for b in (sres.get("bullets") or []) if b and b.strip()][:args.sum_bullets]
                        sections["요약"] = {
                            "text": ytxt,
                            "bullets": ybul,
                            "chunks": ([ytxt] if ytxt else []) + ([f"- {b}" for b in ybul] if ybul else []),
                            "urls": [],
                            "model": sres.get("model"),
                            "ts": sres.get("ts"),
                        }
                        seeds_with_summary += 1
                        sections = {"요약": sections["요약"], **{k: v for k, v in sections.items() if k != "요약"}}
                except Exception as e:
                    LOG.error("[summarize_kor] 실패 seed=%s: %s: %s", seed, type(e).__name__, e)

            if not sections:
                continue

            doc = {
                "seed": seed,
                "title": (sorted([t for t in title_map.get(seed, set()) if t])[:1][0] if title_map.get(seed) else seed),
                "sections": sections,  # ← 각 섹션에 summary 포함(있다면)
                "section_order": [s for s in SECTION_ORDER if s in sections] + [s for s in sections if s not in SECTION_ORDER],
                "meta": meta_map.get(seed, {}),
                "doc_id": stable_doc_id(seed),
                "created_at": datetime.now(timezone.utc).isoformat(),
            }
            if args.top_summary and "요약" in sections:
                doc["summary"] = sections["요약"].get("text", "")
                doc["sum_bullets"] = sections["요약"].get("bullets", [])

            # ------ 인덱싱(문서 단위) ------
            flat_segments = flatten_segments_from_sections(sections)   # 요약 제외
            all_urls = collect_all_urls(sections)
            n_segments = len(flat_segments)

            # Mongo pages + chunks
            if mongo:
                mongo.upsert_page(doc, n_segments=n_segments, all_urls=all_urls)
                ids, texts, metas = mongo.upsert_chunks(doc)
            else:
                ids, texts, metas = [], [], []

            # Chroma 임베딩 + 문서 단위 마킹
            if chroma and n_segments > 0:
                seg_ids = chroma.upsert_embeddings(ids, texts, metas)
                if mongo:
                    mongo.mark_vectorized(doc["doc_id"], seg_ids)
            # --------------------------------

            # JSONL 저장
            out_f.write(json.dumps(doc, ensure_ascii=False) + "\n")
            seeds_written += 1

            if args.per_seed_dir:
                safe = re.sub(r'[\\/:*?"<>|]', '_', seed)[:180] + ".jsonl"
                with open(os.path.join(args.per_seed_dir, safe), "w", encoding="utf-8") as g:
                    g.write(json.dumps(doc, ensure_ascii=False) + "\n")

    LOG.info("Input rows: %d", total_in)
    LOG.info("Kept rows after noise filter: %d", kept)
    LOG.info("Seeds written: %d", seeds_written)
    LOG.info("Seeds with summary: %d", seeds_with_summary)
    LOG.info("Output JSONL: %s", args.out)
    if args.per_seed_dir:
        LOG.info("Per-seed files in: %s", args.per_seed_dir)

if __name__ == "__main__":
    main()
