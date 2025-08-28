# app/vector_store/metrics.py
from __future__ import annotations
import math
from typing import Optional

def _sigmoid_stable(x: float) -> float:
    # sigmoid(x) = 0.5 * (tanh(x/2) + 1) -> overflow 안전
    return 0.5 * (math.tanh(0.5 * x) + 1.0)

def to_similarity(
    distance: Optional[float],
    space: str = "cosine",
    *,
    clip: bool = True,
    alpha: float = 1.0,          # ip/l2 변환 강도
    mapping: str = "default",    # "default" | "exp" (l2용)
) -> Optional[float]:
    """
    distance -> similarity (0..1, 높을수록 유사)
    - cosine: d=1-cos  -> sim=(cos+1)/2 = 1 - d/2
    - l2    : 기본 1/(1+α·d)  또는 mapping="exp"면 exp(-α·d)
    - ip    : sigmoid(α·dot) (단조, 순위 보존)
    """
    if distance is None:
        return None

    d = float(distance)
    s = space.lower()

    if s in ("cos", "cosine", "cos_sim", "cosine_sim"):
        # d in [0,2] -> sim in [1,0]
        sim = 1.0 - (d * 0.5)
    elif s in ("euclidean", "l2", "l2_distance"):
        if mapping == "exp":
            sim = math.exp(-alpha * d)
        else:
            sim = 1.0 / (1.0 + alpha * d)
    elif s in ("ip", "dot", "inner_product"):
        # dot ∈ (-inf, +inf) -> sim ∈ (0,1)
        sim = _sigmoid_stable(alpha * d)
    else:
        # 안전 기본값: cosine 가정
        sim = 1.0 - (d * 0.5)

    if clip:
        if sim < 0.0: sim = 0.0
        if sim > 1.0: sim = 1.0
    return sim
