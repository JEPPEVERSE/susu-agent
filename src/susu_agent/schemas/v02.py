"""v0.2 多 Agent 架构之间传递的结构化 artifact。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VerificationIssue(StrictModel):
    issue_id: str = Field(pattern=r"^issue_[0-9]+$", max_length=100)
    affected_solution_step_ids: list[str] = Field(default_factory=list, max_length=30)
    issue_type: Literal[
        "final_answer_error",
        "step_reasoning_error",
        "lesson_plan_mismatch",
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

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        if self.verdict == "passed" and any(
            issue.severity == "error" for issue in self.issues
        ):
            raise ValueError("A passed verification cannot contain errors.")
        if self.verdict == "needs_revision" and not self.issues:
            raise ValueError("A revision verdict must explain at least one issue.")
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
        return self


class LearningEvidence(StrictModel):
    evidence_id: str = Field(min_length=1, max_length=100)
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    observation: str = Field(min_length=1, max_length=500)
    assessment: Literal["positive", "negative", "mixed", "uncertain"]
    confidence: Literal["low", "medium", "high"]
    source_question_id: str | None = Field(default=None, max_length=100)


class ExecutionStateDelta(StrictModel):
    stage: Literal[
        "understand_task", "recall_knowledge", "make_plan", "execute", "verify", "complete"
    ] | None = None
    current_strategy_node_id: str | None = Field(default=None, max_length=100)
    current_solution_step_id: str | None = Field(default=None, max_length=100)
    completed_solution_step_ids_to_add: list[str] = Field(default_factory=list, max_length=30)
    current_solution_question_id: str | None = Field(default=None, max_length=100)
    completed_solution_question_ids_to_add: list[str] = Field(default_factory=list, max_length=100)
    confirmed_steps_to_add: list[str] = Field(default_factory=list, max_length=20)
    misconceptions_to_add: list[str] = Field(default_factory=list, max_length=10)
    open_question: str | None = Field(default=None, min_length=1, max_length=1_000)
    answered_open_question_summary: str | None = Field(default=None, max_length=500)
    answered_open_question_understanding: Literal[
        "no_idea", "incorrect", "partially_correct", "correct", "unclear"
    ] | None = None
    answered_open_question_assessment: str | None = Field(default=None, max_length=500)
    next_teacher_action: Literal[
        "ask_question", "give_hint", "explain", "verify_answer"
    ] | None = None
    rolling_summary: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def validate_answer_fields(self) -> Self:
        answer_fields = (
            self.answered_open_question_summary,
            self.answered_open_question_understanding,
            self.answered_open_question_assessment,
        )
        if any(value is not None for value in answer_fields) and any(
            value is None for value in answer_fields
        ):
            raise ValueError(
                "An open-question answer requires summary, understanding, and assessment."
            )
        return self


class TeachingExecution(StrictModel):
    schema_version: Literal[1] = 1
    response: str = Field(min_length=1, max_length=8_000)
    assessment: Literal[
        "not_applicable", "no_idea", "incorrect", "partially_correct", "correct", "unclear"
    ]
    state_delta: ExecutionStateDelta
    learning_evidence: list[LearningEvidence] = Field(default_factory=list, max_length=20)
    control_signal: Literal["continue", "replan_required", "complete"] = "continue"
    control_reason: str = Field(default="", max_length=1_000)

    @model_validator(mode="after")
    def validate_turn_contract(self) -> Self:
        delta = self.state_delta
        if self.control_signal == "continue" and delta.open_question is None:
            raise ValueError(
                "A continuing teaching turn must register exactly one open question."
            )
        if self.control_signal == "complete":
            if delta.open_question is not None:
                raise ValueError("A completed teaching turn cannot open a new question.")
            if delta.stage not in {None, "complete"}:
                raise ValueError(
                    "A completed teaching turn cannot set a non-complete stage."
                )
        if self.control_signal == "replan_required" and delta.open_question is not None:
            raise ValueError("A replanning request cannot open a question on the old strategy.")
        if delta.open_question is not None and delta.open_question.strip() not in self.response:
            raise ValueError(
                "The registered open question must appear verbatim in the student-facing response."
            )

        answer_understanding = delta.answered_open_question_understanding
        if self.assessment == "not_applicable" and answer_understanding is not None:
            raise ValueError(
                "An unassessed turn cannot record an answer to an open question."
            )
        if (
            answer_understanding is not None
            and self.assessment != answer_understanding
        ):
            raise ValueError(
                "The turn assessment must match the open-question assessment."
            )
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
    description: str = Field(min_length=1, max_length=300)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    confidence: Literal["low", "medium", "high"]


class MetaKnowledgeCardPatch(StrictModel):
    card_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)


class StudentModelPatch(StrictModel):
    schema_version: Literal[1] = 1
    base_model_version: int = Field(ge=1)
    concept_updates: list[ConceptMasteryPatch] = Field(default_factory=list, max_length=50)
    misconception_updates: list[MisconceptionPatch] = Field(default_factory=list, max_length=20)
    meta_knowledge_cards_to_add: list[MetaKnowledgeCardPatch] = Field(
        default_factory=list, max_length=30
    )
    insufficient_evidence: list[str] = Field(default_factory=list, max_length=30)
