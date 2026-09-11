"""检索相关性、覆盖率和失败分类。"""

from susu_agent.schemas.memory import RetrievalEvidence, RetrievalQuery, RetrievalResult


class RetrievalEvaluator:
    def __init__(self, *, relevance_threshold: float = 0.16) -> None:
        self.relevance_threshold = relevance_threshold

    def evaluate(
        self,
        query: RetrievalQuery,
        evidence: list[RetrievalEvidence],
        *,
        adjacent_domains_available: bool = False,
    ) -> RetrievalResult:
        if not evidence:
            return RetrievalResult(
                query=query,
                evidence=[],
                failure_type="retrieval_empty",
                recommended_action="expand_domain",
                expansion_level=query.expansion_level,
            )
        relevant = [item for item in evidence if item.rerank_score >= self.relevance_threshold]
        if not relevant:
            return RetrievalResult(
                query=query,
                evidence=evidence,
                failure_type="low_relevance",
                confidence=max(item.rerank_score for item in evidence),
                recommended_action="rewrite_query",
                expansion_level=query.expansion_level,
            )
        matched_concepts = {
            feature
            for item in relevant
            for feature in item.matched_features
            if feature == "concept_ids"
        }
        coverage = 1.0 if not query.concept_ids else (1.0 if matched_concepts else 0.0)
        if coverage < 1.0:
            failure = "cross_domain_required" if adjacent_domains_available else "low_coverage"
            return RetrievalResult(
                query=query,
                evidence=relevant,
                failure_type=failure,
                confidence=sum(item.rerank_score for item in relevant) / len(relevant),
                coverage=coverage,
                recommended_action="expand_concept_graph",
                expansion_level=query.expansion_level,
            )
        return RetrievalResult(
            query=query,
            evidence=relevant,
            confidence=sum(item.rerank_score for item in relevant) / len(relevant),
            coverage=coverage,
            recommended_action="use_evidence",
            expansion_level=query.expansion_level,
        )

    @staticmethod
    def classify_agent_failure(
        *,
        schema_valid: bool = True,
        verification_passed: bool = True,
        evidence_sufficient: bool = True,
        reasoning_succeeded: bool = True,
        pedagogically_matched: bool = True,
        evaluator_confident: bool = True,
    ) -> str | None:
        """按保守优先级区分检索之后的处理失败。"""
        if not schema_valid:
            return "schema_invalid"
        if not evaluator_confident:
            return "uncertain"
        if not verification_passed:
            return "verification_failed"
        if not evidence_sufficient:
            return "low_coverage"
        if not reasoning_succeeded:
            return "reasoning_failed"
        if not pedagogically_matched:
            return "pedagogical_mismatch"
        return None
