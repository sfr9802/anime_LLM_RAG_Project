from __future__ import annotations

"""MMR (Maximal Marginal Relevance) utility."""

from typing import Any, Dict, List
import numpy as np
import torch

from rag_demo.app.app.domain.chroma_embeddings import embed_queries, embed_passages


def _mmr(q: str, items: List[Dict[str, Any]], k: int, lam: float = 0.5) -> List[Dict[str, Any]]:
    if not items:
        return items

    vecs: List[np.ndarray] = []
    use_db = True
    for it in items:
        emb = it.get("embedding")
        if emb is None:
            use_db = False
            break
        vecs.append(np.asarray(emb, dtype="float32"))

    if use_db and vecs:
        cvs_np = np.vstack(vecs)
    else:
        texts = [(it.get("text") or "") for it in items]
        cvs_np = np.array(embed_passages(texts))

    qv_np = np.array(embed_queries([q]))[0]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    cvs = torch.from_numpy(cvs_np).to(device)
    qv = torch.from_numpy(qv_np).to(device)

    n = cvs.shape[0]
    if n <= k:
        return items[:k]

    qn = torch.norm(qv) + 1e-8
    cn = torch.norm(cvs, dim=1) + 1e-8
    sim_q = (cvs @ qv) / (qn * cn)

    selected: List[int] = []
    mask = torch.zeros(n, dtype=torch.bool, device=device)
    while len(selected) < k:
        if not selected:
            i = int(torch.argmax(sim_q).item())
        else:
            sel = cvs[torch.tensor(selected, device=device)]
            seln = torch.norm(sel, dim=1) + 1e-8
            sim_div = (cvs @ sel.T) / (cn.unsqueeze(1) * seln.unsqueeze(0))
            sim_div = sim_div.max(dim=1).values
            mmr = lam * sim_q - (1 - lam) * sim_div
            mmr[mask] = -1e9
            i = int(torch.argmax(mmr).item())
        selected.append(i)
        mask[i] = True
        if mask.all():
            break

    return [items[i] for i in selected]


__all__ = ["_mmr"]

