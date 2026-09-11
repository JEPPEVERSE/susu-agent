"""可重建的轻量向量索引；可注入生产 Embedding 实现。"""

import hashlib
import math
from typing import Callable, Iterable, Sequence

from susu_agent.memory.lexical_retriever import tokenize
from susu_agent.schemas.memory import MemoryItem

Vector = list[float]


def hashed_embedding(text: str, dimensions: int = 256) -> Vector:
    vector = [0.0] * dimensions
    for term in tokenize(text):
        digest = hashlib.sha256(term.encode("utf-8")).digest()
        index = int.from_bytes(digest[:4], "big") % dimensions
        vector[index] += 1.0 if digest[4] & 1 else -1.0
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


def cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        return 0.0
    score = sum(a * b for a, b in zip(left, right))
    return max(0.0, min(1.0, score))


class VectorRetriever:
    def __init__(
        self,
        embedder: Callable[[str], Sequence[float]] = hashed_embedding,
        *,
        model_name: str = "local-hashed-v1",
    ) -> None:
        self.embedder = embedder
        self.model_name = model_name

    def score(self, query_text: str, items: Iterable[MemoryItem]) -> dict[str, float]:
        query_vector = self.embedder(query_text)
        return {
            item.memory_id: cosine_similarity(
                query_vector, self.embedder(item.retrieval_text)
            )
            for item in items
        }

