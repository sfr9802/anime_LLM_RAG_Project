from __future__ import annotations
from dataclasses import dataclass
import re
from typing import Any, List, Tuple, Iterable, Union, Optional

# ──────────────────────────────────────────────────────────────────────────────
# 튜닝 포인트: 길이 파라미터
# ──────────────────────────────────────────────────────────────────────────────
MIN_CH = 450     # ≈ 250~300토큰 근사
MAX_CH = 900     # ≈ 500~600토큰 근사
OVERLAP = 120    # 경계 걸침 방지

_ws = re.compile(r"\s+")
# 한국어 종결/문장부호/괄호 대응
_SENT_SEP = re.compile(r'((?:[.!?…]|다\.|요\.|죠\.|네\.|습니다\.|였다\.)["\'」』)]*)\s+')

# ──────────────────────────────────────────────────────────────────────────────
# 기본 유틸
# ──────────────────────────────────────────────────────────────────────────────
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

def greedy_chunk(text: str, min_len: int = MIN_CH, max_len: int = MAX_CH, overlap: int = OVERLAP) -> List[str]:
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

# ──────────────────────────────────────────────────────────────────────────────
# token 스타일 호환(필요할 때만 사용)
# ──────────────────────────────────────────────────────────────────────────────
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

# ──────────────────────────────────────────────────────────────────────────────
# 재창(Windowing): 문자 길이 기반 윈도우로 재조립
# ──────────────────────────────────────────────────────────────────────────────
TextLike = Union[str, Tuple[str, str], Chunk]

def _strip_section_prefix(section: Optional[str], text: str) -> str:
    """make_chunks/fast_chunk에서 붙인 '[section] ' 접두를 중복 방지용으로 제거."""
    if not section:
        return text
    prefix = f"[{section}] "
    return text[len(prefix):] if text.startswith(prefix) else text

def _seed_by_overlap(parts: List[str], overlap: int) -> List[str]:
    """
    방금 내보낸 윈도우의 오른쪽 꼬리에서 overlap 문자 이상을 만족하도록
    뒤에서부터 몇 개 파트를 유지하여 다음 버퍼 시드로 반환.
    """
    keep: List[str] = []
    acc = 0
    for t in reversed(parts):
        add = len(t) + (1 if keep else 0)  # 공백 1 고려
        acc += add
        keep.append(t)
        if acc >= overlap:
            break
    return list(reversed(keep))

def _join_len(parts: List[str]) -> int:
    """parts를 공백 한 칸으로 합칠 때의 총 문자 길이."""
    if not parts:
        return 0
    return sum(len(p) for p in parts) + (len(parts) - 1)

def _split_long_piece(piece: str, max_chars: int, overlap: int) -> List[str]:
    """단일 파트가 max를 크게 초과할 때, 공백 경계 우선으로 잘라낸다(문자 기반)."""
    s = piece.strip()
    if len(s) <= max_chars:
        return [s]
    out: List[str] = []
    i = 0
    n = len(s)
    while i < n:
        j = min(n, i + max_chars)
        cut = j
        # 너무 왼쪽까지는 안 가게 60%~j 범위에서 가장 오른쪽 공백을 찾는다
        space = s.rfind(" ", i + int(max_chars * 0.6), j)
        if space != -1:
            cut = space
        out.append(s[i:cut].strip())
        if cut >= n:
            break
        # 겹침 적용(문자 단위)
        i = max(0, cut - overlap)
        if i <= 0 and out and len(out[-1]) >= n:
            break
    return [t for t in out if t]

def window_by_chars(
    chks: Iterable[TextLike],
    *,
    target: int = MAX_CH,         # 이 근처에서 끊으려 시도
    min_chars: int = MIN_CH,      # 너무 짧으면 한 파트 더 붙이거나 예외적 초과 허용
    max_chars: int = MAX_CH,      # 가능하면 초과하지 않음
    overlap: int = OVERLAP,       # 다음 윈도우로 겹칠 최소 문자 수
    attach_header: bool = True,   # (section, text) 입력인 경우 결과에 섹션 헤더를 재부착
) -> List[TextLike]:
    """
    이미 분해된 청크 배열을 문자 길이 기준 윈도우로 재조립.
    입력/출력 타입 동일 유지: List[str] / List[(section, text)] / List[Chunk]
    """
    chks_list = list(chks)
    if not chks_list:
        return []

    # 입력 타입 판별
    first = chks_list[0]
    if isinstance(first, tuple) and len(first) == 2 and isinstance(first[0], str):
        kind = "tuple"   # (section, text)
    elif isinstance(first, Chunk):
        kind = "chunk"
    elif isinstance(first, str):
        kind = "str"
    else:
        raise TypeError("Unsupported element type in chks")

    # 섹션/텍스트 추출
    texts: List[str] = []
    sections: List[Optional[str]] = []
    metas: List[dict] = []
    for el in chks_list:
        if kind == "tuple":
            sec, txt = el  # type: ignore
            sections.append(sec)
            texts.append(_strip_section_prefix(sec, normalize(txt)))
            metas.append({"section": sec})
        elif kind == "chunk":
            c: Chunk = el  # type: ignore
            sec = c.meta.get("section") if isinstance(c.meta, dict) else None
            sections.append(sec)
            texts.append(normalize(c.text))
            metas.append(dict(c.meta) if isinstance(c.meta, dict) else {})
        else:  # "str"
            sections.append(None)
            texts.append(normalize(el))  # type: ignore
            metas.append({})

    # 공통 섹션 선택(모두 같을 때만 사용)
    uniq_secs = {s for s in sections if s}
    common_section = next(iter(uniq_secs)) if len(uniq_secs) == 1 else None

    out: List[TextLike] = []
    buf_parts: List[str] = []
    buf_src_idx: List[int] = []
    i = 0
    N = len(texts)

    def _emit_window(parts: List[str], idxs: List[int]) -> None:
        if not parts:
            return
        body = " ".join(parts).strip()
        if kind == "tuple":
            sec_for_hdr = common_section or (sections[idxs[0]] if sections[idxs[0]] else "")
            head = f"[{sec_for_hdr}] " if (attach_header and sec_for_hdr) else ""
            out.append((sec_for_hdr or "", head + body))  # type: ignore
        elif kind == "chunk":
            m0 = dict(metas[idxs[0]])
            m0.update({
                "from_idx": idxs[0],
                "to_idx": idxs[-1],
                "parts": len(idxs),
                "section": common_section or m0.get("section")
            })
            out.append(Chunk(text=body, meta=m0))  # type: ignore
        else:
            out.append(body)  # type: ignore

    while i < N:
        part = texts[i]

        # 단일 파트가 과도하게 길면 먼저 쪼개서 처리
        if len(part) > max_chars * 1.2:
            if _join_len(buf_parts) >= min_chars:
                _emit_window(buf_parts, buf_src_idx)
                seed = _seed_by_overlap(buf_parts, overlap)
                if seed:
                    keep_k = len(seed)
                    buf_src_idx = buf_src_idx[-keep_k:]
                    buf_parts = seed
                else:
                    buf_src_idx = []
                    buf_parts = []
            pieces = _split_long_piece(part, max_chars, overlap)
            for k, piece in enumerate(pieces):
                if not piece:
                    continue
                _emit_window([piece], [i])
            i += 1
            continue

        cand_len = _join_len(buf_parts) + (1 if buf_parts else 0) + len(part)
        if cand_len <= max_chars:
            buf_parts.append(part)
            buf_src_idx.append(i)
            will_over = (i + 1 < N) and (_join_len(buf_parts) + 1 + len(texts[i+1]) > max_chars)
            if _join_len(buf_parts) >= target and will_over:
                _emit_window(buf_parts, buf_src_idx)
                seed = _seed_by_overlap(buf_parts, overlap)
                if seed:
                    keep_k = len(seed)
                    buf_src_idx = buf_src_idx[-keep_k:]
                    buf_parts = seed
                else:
                    buf_parts, buf_src_idx = [], []
            i += 1
            continue

        # cand_len이 max 초과
        if _join_len(buf_parts) >= min_chars:
            _emit_window(buf_parts, buf_src_idx)
            seed = _seed_by_overlap(buf_parts, overlap)
            if seed:
                keep_k = len(seed)
                buf_src_idx = buf_src_idx[-keep_k:]
                buf_parts = seed
            else:
                buf_parts, buf_src_idx = [], []
            # 같은 i로 재시도
            continue
        else:
            # min 미만인데도 붙이면 초과 → 예외적으로 초과 허용
            buf_parts.append(part)
            buf_src_idx.append(i)
            _emit_window(buf_parts, buf_src_idx)
            seed = _seed_by_overlap(buf_parts, overlap)
            if seed:
                keep_k = len(seed)
                buf_src_idx = buf_src_idx[-keep_k:]
                buf_parts = seed
            else:
                buf_parts, buf_src_idx = [], []
            i += 1
            continue

    # 남은 꼬리 처리
    if buf_parts:
        tail = " ".join(buf_parts).strip()
        if out and len(tail) < (min_chars // 2):
            if kind == "tuple":
                sec, txt = out[-1]  # type: ignore
                if isinstance(txt, str):
                    out[-1] = (sec, (txt + " " + tail).strip())  # type: ignore
                else:
                    out.append((common_section or "", tail))  # fallback
            elif kind == "chunk":
                last: Chunk = out[-1]  # type: ignore
                last.text = (last.text + " " + tail).strip()
                last.meta["to_idx"] = buf_src_idx[-1] if buf_src_idx else last.meta.get("to_idx", 0)
                last.meta["parts"] = int(last.meta.get("parts", 1)) + len(buf_src_idx)
            else:
                out[-1] = (out[-1] + " " + tail).strip()  # type: ignore
        else:
            _emit_window(buf_parts, buf_src_idx)

    return out
