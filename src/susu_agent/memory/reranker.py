"""可解释的混合精排。"""

from dataclasses import dataclass
from datetime import datetime, timezone

from susu_agent.schemas.memory import MemoryItem, RetrievalQuery


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    item: MemoryItem
    dense_score: float
    lexical_score: float
    metadata_score: float
    total_score: float
    matched_features: tuple[str, ...]


class HybridReranker:
    def rank(
        self,
        query: RetrievalQuery,
        items: list[MemoryItem],
        lexical_scores: dict[str, float],
        dense_scores: dict[str, float],
    ) -> list[RankedCandidate]:
        ranked: list[RankedCandidate] = []
        query_concepts = set(query.concept_ids)
        query_steps = set(query.lesson_plan_step_ids)
        now = datetime.now(timezone.utc)
        for item in items:
            features: list[str] = []
            concept_match = self._overlap(query_concepts, set(item.concept_ids))
            step_match = self._overlap(query_steps, set(item.lesson_plan_step_ids))
            stage_match = 1.0 if query.task_stage in item.task_stages else 0.0
            student_fit = 1.0 if item.student_id and item.student_id == query.student_id else 0.0
            if concept_match:
                features.append("concept_ids")
            if step_match:
                features.append("lesson_plan_step_ids")
            if stage_match:
                features.append("task_stage")
            if student_fit:
                features.append("student_id")
            metadata = (
                concept_match * 0.40
                + step_match * 0.25
                + stage_match * 0.20
                + student_fit * 0.15
            )
            age_days = max(0.0, (now - item.updated_at).total_seconds() / 86_400)
            staleness = min(0.15, age_days / 3650 * 0.15)
            total = (
                dense_scores.get(item.memory_id, 0.0) * 0.30
                + lexical_scores.get(item.memory_id, 0.0) * 0.30
                + metadata * 0.25
                + item.confidence * 0.15
                - staleness
            )
            ranked.append(
                RankedCandidate(
                    item=item,
                    dense_score=dense_scores.get(item.memory_id, 0.0),
                    lexical_score=lexical_scores.get(item.memory_id, 0.0),
                    metadata_score=metadata,
                    total_score=total,
                    matched_features=tuple(features),
                )
            )
        return sorted(ranked, key=lambda candidate: (-candidate.total_score, candidate.item.memory_id))

    @staticmethod
    def _overlap(query: set[str], candidate: set[str]) -> float:
        if not query or not candidate:
            return 0.0
        return len(query & candidate) / len(query)

