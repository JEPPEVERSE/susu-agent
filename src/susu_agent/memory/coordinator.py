"""沿概念图逐级扩大检索范围。"""

from dataclasses import dataclass

from susu_agent.memory.evaluator import RetrievalEvaluator
from susu_agent.memory.router import MemoryRouter
from susu_agent.schemas.memory import MemoryType, RetrievalQuery, RetrievalResult


@dataclass(frozen=True, slots=True)
class ConceptEdge:
    source: str
    relation: str
    target: str


class CrossDomainCoordinator:
    def __init__(
        self,
        router: MemoryRouter,
        evaluator: RetrievalEvaluator | None = None,
    ) -> None:
        self.router = router
        self.evaluator = evaluator or RetrievalEvaluator()

    def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
        current = query
        for level in range(query.expansion_level, 3):
            current = current.model_copy(update={"expansion_level": level})
            if level == 1:
                current = current.model_copy(
                    update={"concept_ids": self._expand_concepts(current.concept_ids)}
                )
            elif level == 2:
                current = current.model_copy(
                    update={"concept_ids": []}
                )
            evidence = self.router.retrieve(current)
            result = self.evaluator.evaluate(
                current,
                evidence,
                adjacent_domains_available=level < 2 and bool(self._concept_edges()),
            )
            if result.failure_type is None:
                return result
            if result.failure_type not in {
                "retrieval_empty", "low_relevance", "low_coverage", "cross_domain_required"
            }:
                return result
        return result

    def _concept_edges(self) -> list[ConceptEdge]:
        items = self.router.repository.list_items()
        edges: list[ConceptEdge] = []
        for item in items:
            if item.memory_type != MemoryType.CONCEPT_GRAPH or item.status.value != "active":
                continue
            for raw in item.metadata.get("edges", []):
                if not isinstance(raw, dict):
                    continue
                if all(isinstance(raw.get(key), str) for key in ("source", "relation", "target")):
                    edges.append(ConceptEdge(raw["source"], raw["relation"], raw["target"]))
        return edges

    def _expand_concepts(self, concept_ids: list[str]) -> list[str]:
        selected = set(concept_ids)
        for edge in self._concept_edges():
            if edge.source in selected:
                selected.add(edge.target)
            if edge.target in selected and edge.relation in {
                "analogous_to", "contrasts_with", "often_confused_with"
            }:
                selected.add(edge.source)
        return list(dict.fromkeys([*concept_ids, *sorted(selected - set(concept_ids))]))
