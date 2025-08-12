import json
import re

INPUT_FILE = "namu_anime_raw.jsonl"
OUTPUT_FILE = "namu_anime_cleaned_final.jsonl"

# --- 공통 푸터/저작권/엔진/운영사 등 ---
BOILERPLATE_PATTERNS = [
    # 공통 푸터/저작권/엔진/운영사
    r"이 저작물은\s*CC BY-NC-SA.*?제외\)",
    r"namu\.wiki",
    r"Impulsado por the seed engine",
    r"Operado por .*?S\.R\.L\.",
    r"Hecho con .*?Asunción.*?Paraguay",
    r"Contáctenos|Términos de uso",
    r"Su zona horaria es\s*[A-Za-z/_\-]+",
    r"This site is protected by reCAPTCHA.*?(Privacy Policy|Terms of Service).*",
    r"apply\.",  # reCAPTCHA/hCaptcha 꼬리
    r"hCaptcha.*?(Privacy Policy|Terms of Service).*",

    # 라이브 피드/최근 변경(숫자 + '초 전'/'1분 전' 등)
    r"^\s*[\w\-./()·]+?\s*(\d+초 전|\d+분 전|1분 전)\s*$",

    # 광고/전화/도메인/키워드
    r"\b\d{2,4}-\d{3,4}-\d{4}\b",             # 전화번호
    r"\bwww\.[\w\-]+\.[\w.]+\b",              # www 도메인
    r"\b[\w\-]+\.(co\.kr|kr|com|net)\b",      # 일반 도메인
    r"(견적문의|오프라인광고|게시대 위치|서비스요금|체인점찾기)",
    r"(전국\s*무료?출장|무이자할부|당일발송|데이터복구)",

    # 무의미 토큰/스팸 토큰
    r"\bwZYMnyDJ\b",
    r"더 보기",

    # 다국어 푸터 잔여
    r"Privacy Policy|Terms of Service|Términos|Contáctenos",
]

# --- 뉴스/연예·스포츠 헤드라인 전용 ---
HEADLINE_PATTERNS = [
    # 따옴표로 시작-끝 + 말줄임표/대괄호 꼬리(전형적 헤드라인)
    r"^[\"“‘][^\"”’]{5,150}[\"”’]\s*[.…]+.*$",
    # 말머리 태그/대괄호형 키워드
    r"\[(대전 현장|현장|단독|종합|영상|포토|속보|인터뷰|오피셜|공식)\]",
    r"(대전\s*현장|현장\s*취재|종합2?보|단독\s*보도)",
    # 언론/연예·스포츠 고유 키워드 및 매체명
    r"(기자|앵커|연합뉴스|뉴시스|OSEN|엑스포츠뉴스|스포츠조선|스포티비뉴스|허프포스트|헤럴드경제|일간스포츠|마이데일리)",
    # 국가 한자 머리말(일/미/중/영/한 등)로 시작하는 헤드라인
    r"^[\s]*[日美中英独獨韓]\s?[^ \n]{2,}.*$",
    # ‘…’ 다중 말줄임과 쉼표 나열형 헤드라인
    r"^[^。\n]{5,200}[.…]{2,}[^。\n]{0,200}$",
]

# --- 기존 노이즈 ---
NOISE_PATTERNS = [
    r"그라비티,.*?라그나로크.*?차별화된 재미 선사할 것",
    r"This site is protected by reCAPTCHA.*?",
    r"recaptcha.*?",
    r"^and the Google$",
    r"^\s*\[?편집\]?\s*$",
    r"^\s*HAPPY NEW YEAR\s*$",
    r"^\s*QnA\s*[:：]?\s*$",
]

KEEP_KEYWORDS = ["등장인물", "설정", "줄거리", "평가", "작품 해설", "배경", "스토리", "세계관", "용어", "작중 설정"]

compiled_noise = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in NOISE_PATTERNS]
compiled_boiler = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in BOILERPLATE_PATTERNS]
compiled_headline = [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in HEADLINE_PATTERNS]
valid_chunk_regex = re.compile(r"[가-힣a-zA-Z0-9]")

# 임곗값 완화 (위키체 보존)
MIN_CHARS = 50
MERGE_TARGET = 240
MAX_CHARS = 2200
MAX_LATIN_RATIO = 0.80
MAX_URL_RATIO = 0.15

def strip_zws(text: str) -> str:
    # 제로폭/비가시 공백류 제거 + 다중 공백 정리
    text = re.sub(r"[\u200B-\u200D\uFEFF]", "", text)
    text = re.sub(r"[ \t\u00A0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def remove_boilerplate(text: str) -> str:
    t = strip_zws(text)
    for pat in compiled_boiler:
        t = pat.sub("", t)
    # 실시간 목록 같은 ‘짧은 줄 나열’ 덩어리 제거(짧은 줄이 과반이면 덩어리 날림)
    lines = [ln for ln in t.splitlines()]
    short = sum(1 for ln in lines if len(ln.strip()) <= 30)
    if lines and short / max(1, len(lines)) >= 0.6:
        return ""
    return t.strip()

def remove_headlines(text: str) -> str:
    t = text
    for pat in compiled_headline:
        t = pat.sub("", t)
    # 한 줄이 전형적 헤드라인 형태(문장부호 과다 + 짧음)면 제거
    lines = []
    for ln in t.splitlines():
        s = ln.strip()
        if not s:
            continue
        # 헤드라인 휴리스틱: 짧고(<= 120자) 구두점/괄호/따옴표 많이 포함
        punct = len(re.findall(r"[\"“”‘’'…\[\]\(\)【】<>]", s))
        if len(s) <= 120 and punct >= 2 and re.search(r"[…\[\]()]", s):
            continue
        lines.append(ln)
    return "\n".join(lines).strip()

def clean_chunk_text(text):
    t = strip_zws(text)
    for pattern in compiled_noise:
        t = pattern.sub("", t)
    t = remove_boilerplate(t)
    t = remove_headlines(t)
    return t.strip()

def has_meaningful_chars(text):
    return bool(valid_chunk_regex.search(text))

def latin_ratio(text):
    if not text: return 1.0
    latin = len(re.findall(r"[A-Za-z]", text))
    return latin / max(1, len(text))

def url_ratio(text):
    if not text: return 0.0
    urls = len(re.findall(r"https?://|www\.", text))
    return urls / max(1, text.count(" ") + 1)

def is_metadata_keyword_hit(doc):
    seed_title = doc.get("metadata", {}).get("seed_title", "").lower()
    title = doc.get("title", "").lower()
    return any(k.lower() in seed_title or k.lower() in title for k in KEEP_KEYWORDS)

def domain_of(url: str) -> str:
    m = re.search(r"https?://([^/]+)/?", url or "", re.I)
    return m.group(1).lower() if m else ""

def drop_low_quality(chunks, url_domain=""):
    kept = []
    latin_cap = 0.90 if "namu.wiki" in url_domain else MAX_LATIN_RATIO
    url_cap = 0.25 if "namu.wiki" in url_domain else MAX_URL_RATIO
    for c in chunks:
        if not has_meaningful_chars(c):
            continue
        if latin_ratio(c) > latin_cap:
            continue
        if url_ratio(c) > url_cap:
            continue
        kept.append(c)
    return kept

def merge_small_chunks(chunks):
    merged = []
    buf = []
    cur = 0
    for c in chunks:
        if cur + len(c) < MERGE_TARGET:
            buf.append(c); cur += len(c) + 2
        else:
            if buf: merged.append("\n".join(buf)); buf, cur = [], 0
            merged.append(c)
    if buf: merged.append("\n".join(buf))
    # 너무 긴 건 적당히 쪼개기
    out = []
    for c in merged:
        if len(c) <= MAX_CHARS:
            out.append(c)
        else:
            # 문장 단위로 쪼개기
            parts = re.split(r"(?<=[.!?。！？])\s+", c)
            acc = ""
            for p in parts:
                if len(acc) + len(p) + 1 > MAX_CHARS:
                    if acc: out.append(acc.strip())
                    acc = p
                else:
                    acc += (" " if acc else "") + p
            if acc: out.append(acc.strip())
    return out

def clean_jsonl():
    total, kept, removed, saved_by_keyword = 0, 0, 0, 0

    with open(INPUT_FILE, "r", encoding="utf-8") as infile, \
         open(OUTPUT_FILE, "w", encoding="utf-8") as outfile:

        for line in infile:
            total += 1
            try:
                doc = json.loads(line)
                url_dom = domain_of(doc.get("url", ""))

                # 문서 수준 보정: 일부 크롤에서 본문이 chunks가 아닌 잘못된 필드에 붙어오는 경우 대비
                raw_chunks = doc.get("chunks", [])
                if isinstance(raw_chunks, str):
                    raw_chunks = [raw_chunks]
                if not raw_chunks:
                    # 혹시 title/metadata에 본문이 섞인 케이스?
                    possible = []
                    for k in ("body", "content", "text"):
                        if k in doc and isinstance(doc[k], str):
                            possible.append(doc[k])
                    if possible:
                        raw_chunks = possible

                # 1) 텍스트 정리 + 노이즈/푸터/헤드라인 제거
                cleaned_chunks = []
                for c in raw_chunks:
                    t = clean_chunk_text(c)
                    if t and len(t) >= MIN_CHARS:
                        cleaned_chunks.append(t)

                # 2) 도메인 특성 반영한 품질 필터
                cleaned_chunks = drop_low_quality(cleaned_chunks, url_domain=url_dom)

                # 3) 병합/분할
                cleaned_chunks = merge_small_chunks(cleaned_chunks)

                # 4) 최종 판단
                if not cleaned_chunks:
                    if is_metadata_keyword_hit(doc):
                        doc["chunks"] = []
                        json.dump(doc, outfile, ensure_ascii=False); outfile.write("\n")
                        kept += 1; saved_by_keyword += 1
                    else:
                        removed += 1
                    continue

                doc["chunks"] = cleaned_chunks
                json.dump(doc, outfile, ensure_ascii=False)
                outfile.write("\n")
                kept += 1

            except json.JSONDecodeError:
                removed += 1

    print(f"✅ 완료: 총 {total}개 중 {kept}개 유지 ({saved_by_keyword}개 키워드 보존), {removed}개 제거")

if __name__ == "__main__":
    clean_jsonl()
