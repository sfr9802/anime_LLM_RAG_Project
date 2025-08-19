import re
from typing import List, Tuple

# 튜닝 포인트: 길이 파라미터
MIN_CH = 450     # ≈ 250~300토큰 근사
MAX_CH = 900     # ≈ 500~600토큰 근사
OVERLAP = 120    # 경계 걸침 방지

_ws = re.compile(r"\s+")
# 한국어 종결/문장부호/괄호 대응
_SENT_SEP = re.compile(
    r'((?:[.!?…]|다\.|요\.|죠\.|네\.|습니다\.|였다\.)["\'」』)]*)\s+'
)

def normalize(text: str) -> str:
    text = (text or "").replace("\u200b"," ").replace("\ufeff"," ")
    text = _ws.sub(" ", text).strip()
    return text

def split_sentences_ko(text: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    sents: List[str] = []
    for p in paras:
        # 2) "문장끝+따옴표/괄호+공백" → "문장끝+따옴표/괄호 + \n" 로 바꿔서 분할
        marked = _SENT_SEP.sub(r"\1\n", p)
        parts = [s.strip() for s in marked.split("\n") if s.strip()]
        for s in parts:
            if len(s) > MAX_CH * 1.2:
                subs = re.split(r"(?:,|;| 그러나 | 하지만 | 그리고 | 또한 )", s)
                for sub in subs:
                    sub = sub.strip()
                    if sub:
                        sents.append(sub)
            else:
                sents.append(s)
    return sents

def greedy_chunk(text: str, min_len=MIN_CH, max_len=MAX_CH, overlap=OVERLAP) -> List[str]:
    text = normalize(text)
    sents = split_sentences_ko(text)
    if not sents: 
        return []
    out: List[str] = []
    buf: List[str] = []
    cur = 0
    for s in sents:
        L = len(s) + (1 if buf else 0)
        if cur + L <= max_len:
            buf.append(s); cur += L
        else:
            # 충분히 찼으면 플러시
            if cur >= min_len:
                chunk = " ".join(buf).strip()
                out.append(chunk)
                # 오버랩: 뒤에서부터 몇 문장 끌어온다
                keep = []
                rem = 0
                for t in reversed(buf):
                    rem += len(t) + 1
                    keep.append(t)
                    if rem >= overlap:
                        break
                buf = list(reversed(keep))  # overlap seed
                cur = sum(len(t) + 1 for t in buf)
                # 새 문장 추가(필요 시 다음 라운드에서 처리)
                if len(s) >= min_len and len(s) <= max_len:
                    buf.append(s); cur += len(s) + 1
                else:
                    # s가 길면 한 문장 더한 뒤 다음 루프에서 잘리도록
                    buf.append(s); cur += len(s) + 1
            else:
                # 최소 길이 못 채웠는데 넘침 → 그냥 끊고 다음
                out.append(" ".join(buf).strip())
                buf = [s]; cur = len(s)
    if buf:
        # 너무 짧은 꼬리면 앞 청크와 합치기 또는 버리기
        tail = " ".join(buf).strip()
        if out and len(tail) < min_len // 2:
            out[-1] = (out[-1] + " " + tail).strip()
        else:
            out.append(tail)
    return out

def make_chunks(text: str, section: str, attach_header: bool = True) -> List[Tuple[str, str]]:
    """Return list of (section, chunk_text). 섹션/헤더를 chunk 프리픽스로 부착."""
    chunks = greedy_chunk(text)
    if attach_header and section:
        prefixed = []
        for c in chunks:
            # 헤더를 프리픽스로 한 줄 넣어 키워드 밀도와 검색 매칭 강화
            prefixed.append((section, f"[{section}] {c}"))
        return prefixed
    return [(section, c) for c in chunks]

def window_by_chars(chunks: List[str], *, target: int = 700, min_chars: int = 350, max_chars: int = 1200, overlap: int = 120) -> List[str]:
    out: List[str] = []
    buf: List[str] = []
    acc = 0

    def flush():
        nonlocal buf, acc
        if not buf: return
        s = " ".join(buf).strip()
        if not s:
            buf.clear(); acc = 0; return
        if len(s) > max_chars:
            i = 0
            n = len(s)
            while i < n:
                j = min(n, i + max_chars)
                out.append(s[i:j])
                i = j - min(overlap, j - i)
        else:
            out.append(s)
        buf.clear(); acc = 0

    for c in chunks:
        t = (c or "").strip()
        if not t: 
            continue
        if acc + len(t) + 1 <= target:
            buf.append(t); acc += len(t) + 1
        else:
            if acc < min_chars:
                buf.append(t); acc += len(t) + 1
                flush()
            else:
                flush()
                buf.append(t); acc = len(t) + 1
    flush()
    return out