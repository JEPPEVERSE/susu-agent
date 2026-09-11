"""v0.3 记忆平面的结构化契约。"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MemoryType(str, Enum):
    LESSON_CHUNK = "lesson_chunk"
    QUESTION_CARD = "question_card"
    MISCONCEPTION_CARD = "misconception_card"
    SOLUTION_PATTERN = "solution_pattern"
    TEACHING_CASE = "teaching_case"
    CONCEPT_GRAPH = "concept_graph"
    STUDENT_MEMORY = "student_memory"
    TEACHER_POLICY = "teacher_policy"


class MemoryScope(str, Enum):
    GLOBAL = "global"
    SUBJECT = "subject"
    STUDENT = "student"
    SESSION = "session"


class MemoryStatus(str, Enum):
    STAGING = "staging"
    ACTIVE = "active"
    QUARANTINED = "quarantined"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class MemoryOperation(str, Enum):
    ADD = "add"
    REINFORCE = "reinforce"
    WEAKEN = "weaken"
    MERGE = "merge"
    SUPERSEDE = "supersede"
    QUARANTINE = "quarantine"
    EXPIRE = "expire"
    ROLLBACK = "rollback"


class Provenance(StrictModel):
    source_type: str = Field(min_length=1, max_length=100)
    source_id: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    created_by: str = Field(default="system", min_length=1, max_length=100)


class CardApplicability(StrictModel):
    degrees_of_freedom_min: int | None = Field(default=None, ge=0, le=100)
    goal_types: list[str] = Field(default_factory=list, max_length=30)
    problem_types: list[str] = Field(default_factory=list, max_length=30)
    lesson_plan_step_ids: list[str] = Field(default_factory=list, max_length=100)
    concept_ids: list[str] = Field(default_factory=list, max_length=100)
    task_stages: list[str] = Field(default_factory=list, max_length=30)

    @field_validator(
        "goal_types",
        "problem_types",
        "lesson_plan_step_ids",
        "concept_ids",
        "task_stages",
    )
    @classmethod
    def unique_filters(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("Card applicability filters must be unique")
        return values

    @field_validator("concept_ids")
    @classmethod
    def stable_concepts(cls, values: list[str]) -> list[str]:
        import re

        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", value) for value in values):
            raise ValueError("Card concept_ids must be stable snake_case identifiers")
        return values


class QuestionCard(StrictModel):
    question_card_id: str = Field(min_length=1, max_length=200)
    question_template: str = Field(min_length=1, max_length=2_000)
    teaching_goal: str = Field(min_length=1, max_length=2_000)
    expected_answer: str = Field(min_length=1, max_length=4_000)
    answer_checkpoints: list[str] = Field(min_length=1, max_length=20)
    hint_ladder: list[str] = Field(default_factory=list, max_length=10)
    applicability: CardApplicability = Field(default_factory=CardApplicability)
    retrieval_text: str = Field(min_length=1, max_length=10_000)


class MisconceptionCard(StrictModel):
    misconception_card_id: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=4_000)
    diagnostic_signals: list[str] = Field(default_factory=list, max_length=20)
    counterexamples: list[str] = Field(default_factory=list, max_length=20)
    correction_strategy: str = Field(min_length=1, max_length=4_000)
    answer_checkpoints: list[str] = Field(default_factory=list, max_length=20)
    applicability: CardApplicability = Field(default_factory=CardApplicability)
    retrieval_text: str = Field(min_length=1, max_length=10_000)


class SolutionPattern(StrictModel):
    solution_pattern_id: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=500)
    problem_signature: str = Field(min_length=1, max_length=2_000)
    strategy: str = Field(min_length=1, max_length=6_000)
    preconditions: list[str] = Field(default_factory=list, max_length=30)
    verification_checks: list[str] = Field(default_factory=list, max_length=30)
    applicability: CardApplicability = Field(default_factory=CardApplicability)
    retrieval_text: str = Field(min_length=1, max_length=10_000)


class MemoryCardCatalog(StrictModel):
    schema_version: Literal[1] = 1
    subject: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=100)
    catalog_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    question_cards: list[QuestionCard] = Field(default_factory=list, max_length=500)
    misconception_cards: list[MisconceptionCard] = Field(
        default_factory=list, max_length=500
    )
    solution_patterns: list[SolutionPattern] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def unique_card_ids(self) -> Self:
        ids = [card.question_card_id for card in self.question_cards]
        ids.extend(card.misconception_card_id for card in self.misconception_cards)
        ids.extend(pattern.solution_pattern_id for pattern in self.solution_patterns)
        if len(ids) != len(set(ids)):
            raise ValueError("Memory Card ids must be unique across a catalog")
        return self


class MemoryItem(StrictModel):
    schema_version: Literal[1] = 1
    memory_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    memory_type: MemoryType
    canonical_text: str = Field(min_length=1, max_length=30_000)
    retrieval_text: str = Field(min_length=1, max_length=30_000)
    subject: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=100)
    task_stages: list[str] = Field(default_factory=list, max_length=30)
    target_agents: list[str] = Field(default_factory=list, max_length=30)
    concept_ids: list[str] = Field(default_factory=list, max_length=100)
    lesson_plan_step_ids: list[str] = Field(default_factory=list, max_length=100)
    scope: MemoryScope = MemoryScope.SUBJECT
    student_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    provenance: Provenance
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    version: int = Field(default=1, ge=1)
    status: MemoryStatus = MemoryStatus.STAGING
    embedding_model: str | None = Field(default=None, max_length=200)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime | None = None

    @field_validator(
        "task_stages", "target_agents", "concept_ids", "lesson_plan_step_ids"
    )
    @classmethod
    def unique_values(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("memory metadata lists must not contain duplicates")
        return values

    @field_validator("concept_ids")
    @classmethod
    def stable_concept_ids(cls, values: list[str]) -> list[str]:
        import re

        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", value) for value in values):
            raise ValueError("concept_ids must be stable snake_case identifiers")
        return values

    @model_validator(mode="after")
    def validate_scope(self) -> Self:
        if self.scope == MemoryScope.STUDENT and not self.student_id:
            raise ValueError("student-scoped memory requires student_id")
        if self.scope == MemoryScope.SESSION and not self.session_id:
            raise ValueError("session-scoped memory requires session_id")
        if self.scope in {MemoryScope.GLOBAL, MemoryScope.SUBJECT} and (
            self.student_id is not None or self.session_id is not None
        ):
            raise ValueError("shared memory cannot carry student_id or session_id")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        card_payload = self.metadata.get("card")
        if self.memory_type == MemoryType.QUESTION_CARD:
            card = QuestionCard.model_validate(card_payload)
            if card.question_card_id != self.memory_id:
                raise ValueError("Question Card id must equal memory_id")
            if card.retrieval_text != self.retrieval_text:
                raise ValueError("Question Card retrieval_text must equal memory projection")
        elif self.memory_type == MemoryType.MISCONCEPTION_CARD:
            card = MisconceptionCard.model_validate(card_payload)
            if card.misconception_card_id != self.memory_id:
                raise ValueError("Misconception Card id must equal memory_id")
            if card.retrieval_text != self.retrieval_text:
                raise ValueError("Misconception Card retrieval_text must equal memory projection")
        elif self.memory_type == MemoryType.SOLUTION_PATTERN:
            pattern = SolutionPattern.model_validate(self.metadata.get("pattern"))
            if pattern.solution_pattern_id != self.memory_id:
                raise ValueError("Solution Pattern id must equal memory_id")
            if pattern.retrieval_text != self.retrieval_text:
                raise ValueError("Solution Pattern retrieval_text must equal memory projection")
        return self


class RetrievalQuery(StrictModel):
    schema_version: Literal[1] = 1
    subject: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=100)
    task_stage: str = Field(min_length=1, max_length=100)
    target_agent: str = Field(min_length=1, max_length=100)
    query_text: str = Field(min_length=1, max_length=20_000)
    concept_ids: list[str] = Field(default_factory=list, max_length=100)
    lesson_plan_step_ids: list[str] = Field(default_factory=list, max_length=100)
    memory_types: list[MemoryType] = Field(default_factory=list, max_length=20)
    student_id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    goal_type: str | None = Field(default=None, max_length=100)
    problem_type: str | None = Field(default=None, max_length=100)
    structural_features: dict[str, Any] = Field(default_factory=dict)
    top_k: int = Field(default=8, ge=1, le=100)
    max_context_chars: int = Field(default=6_000, ge=100, le=100_000)
    expansion_level: int = Field(default=0, ge=0, le=2)

    @field_validator("concept_ids", "lesson_plan_step_ids", "memory_types")
    @classmethod
    def unique_query_filters(cls, values: list[Any]) -> list[Any]:
        if len(values) != len(set(values)):
            raise ValueError("retrieval filters must not contain duplicates")
        return values


class RetrievalEvidence(StrictModel):
    schema_version: Literal[1] = 1
    memory_id: str
    memory_type: MemoryType
    source: str
    matched_features: list[str] = Field(default_factory=list)
    dense_score: float = Field(default=0.0, ge=0.0, le=1.0)
    lexical_score: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata_score: float = Field(default=0.0, ge=0.0, le=1.0)
    rerank_score: float = Field(default=0.0)
    reasoning_path: list[str] = Field(default_factory=list)
    content_excerpt: str = Field(max_length=10_000)
    version: int = Field(ge=1)
    confidence: float = Field(ge=0.0, le=1.0)
    structured_content: dict[str, Any] = Field(default_factory=dict)


class RetrievalResult(StrictModel):
    query: RetrievalQuery
    evidence: list[RetrievalEvidence] = Field(default_factory=list)
    failure_type: Literal[
        "retrieval_empty",
        "low_relevance",
        "low_coverage",
        "cross_domain_required",
        "reasoning_failed",
        "verification_failed",
        "pedagogical_mismatch",
        "schema_invalid",
        "uncertain",
    ] | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    coverage: float = Field(default=0.0, ge=0.0, le=1.0)
    recommended_action: str = "use_evidence"
    expansion_level: int = Field(default=0, ge=0, le=2)
    adopted_memory_ids: list[str] = Field(default_factory=list, max_length=100)

    def to_prompt(self) -> str:
        if not self.evidence:
            return ""
        remaining = self.query.max_context_chars
        blocks: list[str] = []
        for item in self.evidence:
            prefix = (
                f"[{item.memory_type.value}:{item.memory_id} v{item.version}; "
                f"source={item.source}; score={item.rerank_score:.3f}]\n"
            )
            available = max(0, remaining - len(prefix))
            if available == 0:
                break
            excerpt = item.content_excerpt[:available]
            if len(excerpt) < len(item.content_excerpt) and available > 1:
                excerpt = excerpt[:-1] + "…"
            block = prefix + excerpt
            blocks.append(block)
            remaining -= len(block)
        return "\n\n".join(blocks)


class MemoryUpdateProposal(StrictModel):
    schema_version: Literal[1] = 1
    proposal_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,199}$")
    operation: MemoryOperation
    target_memory_id: str | None = Field(default=None, max_length=200)
    candidate_content: MemoryItem | None = None
    supporting_evidence_ids: list[str] = Field(default_factory=list, max_length=200)
    evidence_source_ids: list[str] = Field(default_factory=list, max_length=100)
    counterexample_ids: list[str] = Field(default_factory=list, max_length=200)
    rollback_version: int | None = Field(default=None, ge=1)
    proposed_confidence: float = Field(ge=0.0, le=1.0)
    scope: MemoryScope
    risk_flags: list[str] = Field(default_factory=list, max_length=50)
    required_reviewers: list[
        Literal["math", "duplicate_conflict", "pedagogy", "privacy", "human"]
    ] = Field(default_factory=list)
    status: Literal["pending", "approved", "rejected", "applied"] = "pending"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_operation(self) -> Self:
        if self.operation == MemoryOperation.ADD and self.candidate_content is None:
            raise ValueError("add requires candidate_content")
        if self.operation == MemoryOperation.ADD and self.target_memory_id is not None:
            raise ValueError("add cannot target an existing memory")
        if self.operation != MemoryOperation.ADD and not self.target_memory_id:
            raise ValueError("non-add operations require target_memory_id")
        if self.operation in {MemoryOperation.MERGE, MemoryOperation.SUPERSEDE} and (
            self.candidate_content is None
        ):
            raise ValueError("merge and supersede require candidate_content")
        if self.operation == MemoryOperation.ROLLBACK and self.rollback_version is None:
            raise ValueError("rollback requires rollback_version")
        if self.operation != MemoryOperation.ROLLBACK and self.rollback_version is not None:
            raise ValueError("rollback_version is only valid for rollback")
        if self.operation not in {
            MemoryOperation.ADD,
            MemoryOperation.MERGE,
            MemoryOperation.SUPERSEDE,
        } and self.candidate_content is not None:
            raise ValueError("this operation cannot carry candidate_content")
        if (
            self.operation == MemoryOperation.MERGE
            and self.candidate_content is not None
            and self.candidate_content.memory_id != self.target_memory_id
        ):
            raise ValueError("merge candidate must preserve target_memory_id")
        if self.candidate_content and self.candidate_content.scope != self.scope:
            raise ValueError("proposal and candidate scopes must match")
        if len(self.supporting_evidence_ids) != len(set(self.supporting_evidence_ids)):
            raise ValueError("supporting evidence ids must be unique")
        if len(self.evidence_source_ids) != len(set(self.evidence_source_ids)):
            raise ValueError("evidence source ids must be unique")
        if self.scope in {MemoryScope.GLOBAL, MemoryScope.SUBJECT} and self.operation in {
            MemoryOperation.ADD, MemoryOperation.MERGE, MemoryOperation.SUPERSEDE
        }:
            required = {"privacy", "duplicate_conflict", "pedagogy"}
            if self.candidate_content and self.candidate_content.subject == "math":
                required.add("math")
            if not required.issubset(set(self.required_reviewers)):
                raise ValueError(
                    f"shared semantic memory requires reviewers: {sorted(required)!r}"
                )
        return self
