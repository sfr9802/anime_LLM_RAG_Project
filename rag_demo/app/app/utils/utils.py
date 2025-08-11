import re

_ws = re.compile(r"\s+")
def normalize_text(s: str) -> str:
    s = s.replace("\u200b", " ").replace("\ufeff", " ")
    s = _ws.sub(" ", s).strip()
    return s
