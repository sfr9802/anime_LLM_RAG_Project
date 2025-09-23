from typing import List, Optional, Literal, Callable, Any, Dict
import os
import numpy as np

def _normalize(v: np.ndarray) -> np.ndarray:
    if v.size == 0:
        return v.astype("float32")
    denom = np.linalg.norm(v, axis=1, keepdims=True) + 1e-8
    return (v / denom).astype("float32")
