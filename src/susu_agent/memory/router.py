"""统一记忆路由、访问控制和混合检索。"""

from datetime import datetime, timezone
from typing import Iterable

from susu_agent.memory.lexical_retriever import LexicalRetriever
from susu_agent.memory.repositories import MemoryRepository
from susu_agent.memory.reranker import HybridReranker
from susu_agent.memory.vector_retriever import VectorRetriever
from susu_agent.schemas.memory import (
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    RetrievalEvidence,
    RetrievalQuery,
)


class MemoryRouter:
    def __init__(
        self,
        repository: MemoryRepository,
        *,
        lexical_retriever: LexicalRetriever | None = None,
        vector_retriever: VectorRetriever | None = None,
        reranker: HybridReranker | None = None,
    ) -> None:
        self.repository = repository
        self.lexical = lexical_retriever or LexicalRetriever()
        self.vector = vector_retriever or VectorRetriever()
        self.reranker = reranker or HybridReranker()

    def retrieve(self, query: RetrievalQuery) -> list[RetrievalEvidence]:
        indexed_ids = self.repository.indexed_ids()
        items = [
            item
            for item in self.repository.list_items(statuses=[MemoryStatus.ACTIVE])
            if item.memory_id in indexed_ids
            and self._is_visible(item, query)
            and self._is_applicable(item, query)
        ]
        lexical = self.lexical.score(query.query_text, items)
        dense = self.vector.score(query.query_text, items)
        ranked = self.reranker.rank(query, items, lexical, dense)[: query.top_k]
        evidence = [
            RetrievalEvidence(
                memory_id=candidate.item.memory_id,
                memory_type=candidate.item.memory_type,
                source=(
                    f"{candidate.item.provenance.source_type}:"
                    f"{candidate.item.provenance.source_id}"
                ),
                matched_features=list(candidate.matched_features),
                dense_score=candidate.dense_score,
                lexical_score=candidate.lexical_score,
                metadata_score=candidate.metadata_score,
                rerank_score=candidate.total_score,
                reasoning_path=list(
                    candidate.item.metadata.get("reasoning_path", [])
                ),
                content_excerpt=candidate.item.canonical_text,
                version=candidate.item.version,
                confidence=candidate.item.confidence,
                structured_content=dict(candidate.item.metadata.get("card", {})),
            )
            for candidate in ranked
        ]
        self.repository.record_event(
            "retrieval_performed",
            {
                "task_stage": query.task_stage,
                "target_agent": query.target_agent,
                "memory_ids": [item.memory_id for item in evidence],
                "expansion_level": query.expansion_level,
            },
        )
        return evidence

    def record_adoption(
        self, memory_ids: Iterable[str], *, session_id: str | None = None
    ) -> None:
        """记录召回证据是否进入最终决策，不修改记忆置信度。"""
        known = self.repository.indexed_ids()
        selected = list(dict.fromkeys(value for value in memory_ids if value in known))
        self.repository.record_event(
            "retrieval_adopted", {"memory_ids": selected, "session_id": session_id}
        )

    @staticmethod
    def _is_visible(item: MemoryItem, query: RetrievalQuery) -> bool:
        now = datetime.now(timezone.utc)
        if item.subject != query.subject:
            return False
        if item.expires_at is not None and item.expires_at <= now:
            return False
        if query.memory_types and item.memory_type not in query.memory_types:
            return False
        if item.task_stages and query.task_stage not in item.task_stages:
            return False
        if item.target_agents and query.target_agent not in item.target_agents:
            return False
        if item.scope == MemoryScope.STUDENT and item.student_id != query.student_id:
            return False
        if item.scope == MemoryScope.SESSION and item.session_id != query.session_id:
            return False
        if item.student_id is not None and item.student_id != query.student_id:
            return False
        return True

    @staticmethod
    def _is_applicable(item: MemoryItem, query: RetrievalQuery) -> bool:
        card = item.metadata.get("card", {})
        applicability = (
            card.get("applicability", {})
            if isinstance(card, dict)
            else item.metadata.get("applicability", {})
        )
        if not applicability:
            applicability = item.metadata.get("applicability", {})
        if not isinstance(applicability, dict):
            return False
        task_stages = applicability.get("task_stages", [])
        if task_stages and query.task_stage not in task_stages:
            return False
        goal_types = applicability.get("goal_types", [])
        if goal_types and query.goal_type and query.goal_type not in goal_types:
            return False
        problem_types = applicability.get("problem_types", [])
        query_problem_type = query.problem_type
        if problem_types and query_problem_type and query_problem_type not in problem_types:
            return False
        minimum = applicability.get("degrees_of_freedom_min")
        actual = query.structural_features.get("degrees_of_freedom")
        if minimum is not None and actual is not None and actual < minimum:
            return False
        required_concepts = set(applicability.get("concept_ids", []))
        if required_concepts and query.concept_ids and not (
            required_concepts & set(query.concept_ids)
        ):
            return False
        required_steps = set(applicability.get("lesson_plan_step_ids", []))
        if required_steps and query.lesson_plan_step_ids and not (
            required_steps & set(query.lesson_plan_step_ids)
        ):
            return False
        return True
