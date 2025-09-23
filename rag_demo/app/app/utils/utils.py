import re

_ws = re.compile(r"\s+")
def normalize_text(s: str) -> str:
    s = s.replace("\u200b", " ").replace("\ufeff", " ")
    s = _ws.sub(" ", s).strip()
    return s

import errno
import tempfile
import os
from typing import List, Dict, Any
import json

def _atomic_write_jsonl(path: str, rows: List[Dict[str, Any]]) :
    dir_path = os.path.dirname(path)
    os.makedirs(dir_path or ".", exist_ok=True)
    
    folder, tmp_path = tempfile.mkstemp(prefix=".tmp_",dir=dir_path or ".")
    try :
        with os.fdopen(folder, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dump(r, ensure_ascii=False) + "\n")
        os.replace(tmp_path, path)
    except Exception :
        try:
            os.remove(tmp_path)
        except OSError :
            pass
        raise

def _read_jsonl(path: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
        return rows
    
    
from typing import List, Optional, Literal, Callable, Any, Dict
import os
import numpy as np

def _normalize(v: np.ndarray) -> np.ndarray:
    if v.size == 0:
        return v.astype("float32")
    denom = np.linalg.norm(v, axis=1, keepdims=True) + 1e-8
    return (v / denom).astype("float32")
