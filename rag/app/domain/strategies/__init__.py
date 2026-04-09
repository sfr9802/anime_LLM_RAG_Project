from app.domain.strategies.baseline import BaselineStrategy
from app.domain.strategies.chroma_only import ChromaOnlyStrategy

STRATEGIES = {
    "baseline": BaselineStrategy(),
    "chroma_only": ChromaOnlyStrategy(),
}
