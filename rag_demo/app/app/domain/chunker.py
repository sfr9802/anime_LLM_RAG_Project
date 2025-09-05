from __future__ import annotations
from dataclasses import dataclass
import re
from typing import List, Tuple, Iterable

# 튜닝 포인트: 길이 파라미터
MIN_CH = 450     # ≈ 250~300토큰 근사
MAX_CH = 900     # ≈ 500~600토큰 근사
OVERLAP = 120    # 경계 걸침 방지

_ws = re.compile(r"\s+")
# 한국어 종결/문장부호/괄호 대응
_SENT_SEP = re.compile(r'((?:[.!?…]|다\.|요\.|죠\.|네\.|습니다\.|였다\.)["\'」』)]*)\s+')

def normalize(text: str) -> str:
    text = (text or "").replace("\u200b", " ").replace("\ufeff", " ")
    text = _ws.sub(" ", text).strip()
    return text

def split_sentences_ko(text: str) -> List[str]:
    paras = [p.strip() for p in re.split(r"\n{2,}", text or "") if p.strip()]
    sents: List[str] = []
    for p in paras:
        marked = _SENT_SEP.sub(r"\1\n", p)
        parts = [s.strip() for s in marked.split("\n") if s.strip()]
        for s in parts:
            if len(s) > MAX_CH * 1.2:
                subs = re.split(r"(?:,|;| 그러나 | 하지만 | 그리고 | 또한 )", s)
                for sub in subs:
                    sub = (sub or "").strip()
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
            if cur >= min_len:
                chunk = " ".join(buf).strip()
                out.append(chunk)
                # 오버랩: 뒤에서 몇 문장 끌어온다
                keep = []
                rem = 0
                for t in reversed(buf):
                    rem += len(t) + 1
                    keep.append(t)
                    if rem >= overlap:
                        break
                buf = list(reversed(keep))  # overlap seed
                cur = sum(len(t) + 1 for t in buf)
                buf.append(s); cur += len(s) + 1
            else:
                out.append(" ".join(buf).strip())
                buf = [s]; cur = len(s)
    if buf:
        tail = " ".join(buf).strip()
        if out and len(tail) < min_len // 2:
            out[-1] = (out[-1] + " " + tail).strip()
        else:
            out.append(tail)
    return out

def make_chunks(text: str, section: str, attach_header: bool = True) -> List[Tuple[str, str]]:
    """(section, chunk_text) 리스트 반환. 헤더를 chunk 프리픽스로 부착."""
    chunks = greedy_chunk(text)
    if attach_header and section:
        prefixed = []
        for c in chunks:
            prefixed.append((section, f"[{section}] {c}"))
        return prefixed
    return [(section, c) for c in chunks]

def fast_chunk(text: str, section: str, *, target: int = 900, max_chars: int = 1600, overlap: int = 150) -> List[Tuple[str, str]]:
    """
    문장분리 없이 문자 기반 윈도우. 인제스트용 고속 경로.
    반환: List[(section, chunk_text)]
    """
    t = normalize(text)
    out: List[Tuple[str, str]] = []
    if not t:
        return out
    n = len(t)
    i = 0
    header = f"[{section}] " if section else ""
    while i < n:
        j = min(n, i + max_chars)
        piece = t[i:j]
        out.append((section, header + piece))
        if j >= n:
            break
        i = j - overlap  # 걸침
    return out

# --- token 스타일 호환(필요할 때만 사용) ------------------------------------
@dataclass
class Chunk:
    text: str
    meta: dict

def chunk_text(text: str, max_tokens: int = 480, stride: int = 120) -> Iterable[Chunk]:
    """
    간단 호환 버전: 토큰 대신 문자 길이로 근사.
    """
    text = normalize(text)
    max_chars = int(max_tokens * 3)   # 대략적 근사
    overlap = int(stride * 3)
    n = len(text)
    if n == 0:
        return []
    chunks: List[Chunk] = []
    i = 0
    part = 0
    while i < n:
        j = min(n, i + max_chars)
        piece = text[i:j]
        chunks.append(Chunk(text=piece, meta={"subsection": f"part-{part}"}))
        if j >= n:
            break
        i = j - overlap
        part += 1
    return chunks
