"""无外部依赖的 BM25 风格词法召回。"""

import math
import re
from collections import Counter
from typing import Iterable

from susu_agent.schemas.memory import MemoryItem


def tokenize(text: str) -> list[str]:
    normalized = text.casefold()
    latin = re.findall(r"[a-z0-9_]+", normalized)
    chinese_runs = re.findall(r"[\u3400-\u9fff]+", normalized)
    chinese: list[str] = []
    for run in chinese_runs:
        chinese.extend(run)
        chinese.extend(run[index : index + 2] for index in range(len(run) - 1))
    return latin + chinese


class LexicalRetriever:
    def score(self, query_text: str, items: Iterable[MemoryItem]) -> dict[str, float]:
        documents = list(items)
        if not documents:
            return {}
        query_terms = set(tokenize(query_text))
        if not query_terms:
            return {item.memory_id: 0.0 for item in documents}
        term_counts = [Counter(tokenize(item.retrieval_text)) for item in documents]
        lengths = [sum(counts.values()) for counts in term_counts]
        average_length = sum(lengths) / max(len(lengths), 1) or 1.0
        document_frequency = {
            term: sum(1 for counts in term_counts if term in counts)
            for term in query_terms
        }
        raw: list[float] = []
        for counts, length in zip(term_counts, lengths):
            value = 0.0
            for term in query_terms:
                frequency = counts.get(term, 0)
                if frequency == 0:
                    continue
                inverse = math.log(
                    1 + (len(documents) - document_frequency[term] + 0.5)
                    / (document_frequency[term] + 0.5)
                )
                value += inverse * frequency * 2.2 / (
                    frequency + 1.2 * (0.25 + 0.75 * length / average_length)
                )
            raw.append(value)
        maximum = max(raw, default=0.0)
        return {
            item.memory_id: (value / maximum if maximum > 0 else 0.0)
            for item, value in zip(documents, raw)
        }

