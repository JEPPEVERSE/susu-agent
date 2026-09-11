"""v0.3 Agent artifact；模块名为 v0.2 调用方保留兼容。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from susu_agent.schemas.memory import MemoryUpdateProposal


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationIssue(StrictModel):
    issue_id: str = Field(pattern=r"^issue_[0-9]+$", max_length=100)
    affected_solution_step_ids: list[str] = Field(default_factory=list, max_length=30)
    issue_type: Literal[
        "final_answer_error",
        "step_reasoning_error",
        "derivation_gap",
        "condition_omission",
        "lesson_plan_mismatch",
        "evidence_insufficient",
    ]
    severity: Literal["warning", "error"]
    evidence: str = Field(min_length=1, max_length=2_000)
    revision_instruction: str = Field(min_length=1, max_length=2_000)


class VerificationReport(StrictModel):
    schema_version: Literal[1] = 1
    verdict: Literal["passed", "needs_revision"]
    summary: str = Field(min_length=1, max_length=2_000)
    checked_solution_step_ids: list[str] = Field(default_factory=list, max_length=30)
    issues: list[VerificationIssue] = Field(default_factory=list, max_length=30)
    confidence: Literal["low", "medium", "high"]
    checked_condition_indices: list[int] = Field(default_factory=list, max_length=50)
    evidence_sufficient: bool = True

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        if self.verdict == "passed" and any(
            issue.severity == "error" for issue in self.issues
        ):
            raise ValueError("A passed verification cannot contain errors.")
        if self.verdict == "needs_revision" and not self.issues:
            raise ValueError("A revision verdict must explain at least one issue.")
        if self.verdict == "passed" and not self.evidence_sufficient:
            raise ValueError("A passed verification requires sufficient evidence.")
        if not self.evidence_sufficient and not any(
            issue.issue_type == "evidence_insufficient" for issue in self.issues
        ):
            raise ValueError("Insufficient evidence requires an evidence issue.")
        if len(self.checked_condition_indices) != len(
            set(self.checked_condition_indices)
        ) or any(index < 0 for index in self.checked_condition_indices):
            raise ValueError("Checked condition indices must be unique and non-negative.")
        return self


class TeachingTransition(StrictModel):
    condition: Literal[
        "correct",
        "partially_correct",
        "incorrect",
        "no_idea",
        "unclear",
        "student_requests_solution",
    ]
    next_node_id: str | None = Field(default=None, max_length=100)
    action: Literal["advance", "retry", "give_hint", "explain", "complete", "replan"]


class TeachingStrategyNode(StrictModel):
    node_id: str = Field(pattern=r"^teach_[0-9]+$", max_length=100)
    solution_step_id: str | None = Field(default=None, max_length=100)
    solution_question_id: str | None = Field(default=None, max_length=100)
    question_card_id: str | None = Field(default=None, max_length=200)
    retrieval_evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    goal: str = Field(min_length=1, max_length=1_000)
    teaching_action: Literal["ask_question", "give_hint", "explain", "verify_answer"]
    prompt_intent: str = Field(min_length=1, max_length=1_000)
    answer_checkpoints: list[str] = Field(default_factory=list, max_length=10)
    hint_ladder: list[str] = Field(default_factory=list, max_length=4)
    disclosure_boundary: str = Field(min_length=1, max_length=1_000)
    transitions: list[TeachingTransition] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def validate_transitions(self) -> Self:
        conditions = [transition.condition for transition in self.transitions]
        if len(conditions) != len(set(conditions)):
            raise ValueError("A teaching node cannot define duplicate transition conditions.")
        invalid_terminal_targets = [
            transition.condition
            for transition in self.transitions
            if transition.action in {"complete", "replan"}
            and transition.next_node_id is not None
        ]
        if invalid_terminal_targets:
            raise ValueError("Complete and replan transitions cannot target another node.")
        if self.question_card_id is not None and self.teaching_action != "ask_question":
            raise ValueError("Question Cards can only be bound to question nodes.")
        if len(self.retrieval_evidence_ids) != len(set(self.retrieval_evidence_ids)):
            raise ValueError("Node retrieval evidence ids must be unique.")
        return self


class AnticipatedDifficulty(StrictModel):
    difficulty_id: str = Field(pattern=r"^difficulty_[0-9]+$", max_length=100)
    related_solution_step_ids: list[str] = Field(default_factory=list, max_length=20)
    description: str = Field(min_length=1, max_length=500)
    evidence_source: Literal["problem_structure", "student_model", "both"]
    likelihood: Literal["low", "medium", "high"]
    response_plan: str = Field(min_length=1, max_length=1_000)


class TeachingStrategy(StrictModel):
    schema_version: Literal[1] = 1
    strategy_id: str = Field(min_length=1, max_length=100)
    summary: str = Field(min_length=1, max_length=2_000)
    initial_node_id: str | None = Field(default=None, max_length=100)
    nodes: list[TeachingStrategyNode] = Field(default_factory=list, max_length=100)
    anticipated_difficulties: list[AnticipatedDifficulty] = Field(
        default_factory=list, max_length=30
    )
    completion_criteria: list[str] = Field(default_factory=list, max_length=20)
    replan_triggers: list[str] = Field(default_factory=list, max_length=20)
    retrieval_evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    retrieval_failure_type: Literal[
        "retrieval_empty",
        "low_relevance",
        "low_coverage",
        "cross_domain_required",
        "uncertain",
    ] | None = None

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Teaching strategy node ids must be unique.")
        known = set(node_ids)
        if self.initial_node_id is not None and self.initial_node_id not in known:
            raise ValueError("The initial teaching node does not exist.")
        unknown = {
            transition.next_node_id
            for node in self.nodes
            for transition in node.transitions
            if transition.next_node_id is not None and transition.next_node_id not in known
        }
        if unknown:
            raise ValueError(f"Teaching transitions reference unknown nodes: {sorted(unknown)!r}.")
        difficulty_ids = [
            difficulty.difficulty_id for difficulty in self.anticipated_difficulties
        ]
        if len(difficulty_ids) != len(set(difficulty_ids)):
            raise ValueError("Anticipated difficulty ids must be unique.")
        if len(self.retrieval_evidence_ids) != len(set(self.retrieval_evidence_ids)):
            raise ValueError("Strategy retrieval evidence ids must be unique.")
        return self


class LearningEvidence(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=100)
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    observation: str = Field(min_length=1, max_length=500)
    assessment: Literal["positive", "negative", "mixed", "uncertain"]
    confidence: Literal["low", "medium", "high"]
    source_question_id: str | None = Field(default=None, max_length=100)
    misconception_card_ids: list[str] = Field(default_factory=list, max_length=20)
    retrieval_evidence_ids: list[str] = Field(default_factory=list, max_length=30)


class ExecutionStateDelta(StrictModel):
    open_question: str | None = Field(default=None, min_length=1, max_length=1_000)
    open_question_target_checkpoint_indices: list[int] = Field(
        default_factory=list, max_length=10
    )
    answered_open_question_summary: str | None = Field(default=None, max_length=500)
    answered_open_question_feedback: str | None = Field(default=None, max_length=500)
    satisfied_checkpoint_indices_to_add: list[int] = Field(
        default_factory=list, max_length=10
    )
    conversation_summary: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_answer_fields(self) -> Self:
        answer_fields = (
            self.answered_open_question_summary,
            self.answered_open_question_feedback,
        )
        if any(value is not None for value in answer_fields) and any(
            value is None for value in answer_fields
        ):
            raise ValueError(
                "An open-question answer requires both summary and feedback."
            )
        return self


class TeachingExecution(StrictModel):
    schema_version: Literal[1] = 1
    feedback: str = Field(default="", max_length=6_900)
    assessment: Literal[
        "not_applicable",
        "no_idea",
        "incorrect",
        "partially_correct",
        "correct",
        "unclear",
        "student_requests_solution",
    ]
    state_delta: ExecutionStateDelta
    learning_evidence: list[LearningEvidence] = Field(default_factory=list, max_length=20)
    diagnosed_misconception_card_ids: list[str] = Field(
        default_factory=list, max_length=20
    )
    retrieval_evidence_ids: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def validate_turn_contract(self) -> Self:
        delta = self.state_delta
        if delta.open_question is None and delta.open_question_target_checkpoint_indices:
            raise ValueError(
                "Checkpoint targets require an open question."
            )
        if not self.feedback.strip() and delta.open_question is None:
            raise ValueError("A teaching turn must contain feedback or an open question.")
        if len(self.retrieval_evidence_ids) != len(set(self.retrieval_evidence_ids)):
            raise ValueError("Execution retrieval evidence ids must be unique.")
        if len(self.diagnosed_misconception_card_ids) != len(
            set(self.diagnosed_misconception_card_ids)
        ):
            raise ValueError("Diagnosed Misconception Card ids must be unique.")
        return self


class ConceptMasteryPatch(StrictModel):
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    subject: Literal["math", "chinese", "english", "physics", "chemistry", "biology"]
    proposed_mastery: Literal["unknown", "learning", "proficient", "mastered"]
    evidence_summary: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    confidence: Literal["low", "medium", "high"]


class MisconceptionPatch(StrictModel):
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    subject: Literal["math", "chinese", "english", "physics", "chemistry", "biology"]
    description: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    confidence: Literal["low", "medium", "high"]


class MetaKnowledgeCardPatch(StrictModel):
    card_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)


class SubjectLevelPatch(StrictModel):
    subject: Literal["math", "chinese", "english", "physics", "chemistry", "biology"]
    proposed_state: Literal[
        "unassessed", "foundation", "developing", "proficient", "advanced"
    ]
    evidence_summary: str = Field(min_length=1, max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    confidence: Literal["low", "medium", "high"]


class StudentModelPatch(StrictModel):
    schema_version: Literal[1] = 1
    base_model_version: int = Field(ge=1)
    concept_updates: list[ConceptMasteryPatch] = Field(default_factory=list, max_length=50)
    misconception_updates: list[MisconceptionPatch] = Field(default_factory=list, max_length=20)
    subject_level_updates: list[SubjectLevelPatch] = Field(
        default_factory=list, max_length=6
    )
    meta_knowledge_cards_to_add: list[MetaKnowledgeCardPatch] = Field(
        default_factory=list, max_length=30
    )
    insufficient_evidence: list[str] = Field(default_factory=list, max_length=30)
    memory_update_proposals: list[MemoryUpdateProposal] = Field(
        default_factory=list, max_length=20
    )
