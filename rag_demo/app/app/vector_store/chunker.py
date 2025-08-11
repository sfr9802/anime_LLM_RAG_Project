import re
from typing import List, Tuple

MIN_CH = 200
MAX_CH = 900

def split_sentences(text: str) -> List[str]:
    # 한국어 문장 단위 대충 자르기
    sents = re.split(r"(?<=[\.!?…]|다\.)\s+", text)
    return [s.strip() for s in sents if s and len(s.strip()) > 0]

def greedy_chunk(text: str, min_len=MIN_CH, max_len=MAX_CH) -> List[str]:
    sents = split_sentences(text)
    out, buf = [], []
    cur = 0
    for s in sents:
        if cur + len(s) <= max_len:
            buf.append(s); cur += len(s) + 1
        else:
            if cur >= min_len:
                out.append(" ".join(buf))
                buf, cur = [s], len(s)
            else:
                # 최소길이 못채웠는데 넘침 → 그냥 끊고 다음
                out.append(" ".join(buf))
                buf, cur = [s], len(s)
    if buf:
        out.append(" ".join(buf))
    # 너무 짧은 꼬리 합치기
    if len(out) >= 2 and len(out[-1]) < min_len//2:
        out[-2] = out[-2] + " " + out[-1]
        out.pop()
    return out

def make_chunks(text: str, section: str) -> List[Tuple[str, str]]:
    """Return list of (section, chunk_text)"""
    chunks = greedy_chunk(text)
    return [(section, c) for c in chunks]
