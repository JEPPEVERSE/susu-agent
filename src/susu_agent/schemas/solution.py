"""学科求解 Agent 的结构化输出模型。"""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """拒绝模型输出 Schema 之外的字段。"""

    model_config = ConfigDict(extra="forbid")


ConceptId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)]


class TutorQuestion(StrictModel):
    """Tutor 在某个解题步骤中可以逐步提出的问题。"""

    question_id: str = Field(pattern=r"^question_[0-9]+$", max_length=100)
    question: str = Field(min_length=1, max_length=500)
    difficulty: Literal["foundation", "standard", "advanced"] = "standard"
    teaching_goal: str = Field(min_length=1, max_length=300)
    expected_answer: str = Field(min_length=1, max_length=600)
    answer_checkpoints: list[str] = Field(default_factory=list, max_length=5)
    hint_ladder: list[str] = Field(default_factory=list, max_length=3)


class SolutionStep(StrictModel):
    """依照教案形成的一步题目级解决过程。"""

    solution_step_id: str = Field(pattern=r"^step_[0-9]+$", max_length=100)
    lesson_plan_step_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=300)
    derivation: str = Field(
        min_length=1,
        max_length=1_500,
        description="可核验的数学推导摘要，不记录模型的隐藏思维过程。",
    )
    result: str = Field(min_length=1, max_length=800)
    concept_ids: list[ConceptId] = Field(default_factory=list, max_length=10)
    tutor_questions: list[TutorQuestion] = Field(default_factory=list, max_length=4)


class Solution(StrictModel):
    """一份题目级、教案驱动且供 Tutor 内部使用的解题计划。"""

    schema_version: Literal[2] = 2
    goal: str = Field(min_length=1, max_length=500)
    known_conditions: list[str] = Field(default_factory=list, max_length=20)
    assumptions: list[str] = Field(default_factory=list, max_length=10)
    strategy_summary: str = Field(min_length=1, max_length=800)
    steps: list[SolutionStep] = Field(default_factory=list, max_length=12)
    final_answer: str = Field(min_length=1, max_length=1_500)
    verification: list[str] = Field(default_factory=list, max_length=5)

    @model_validator(mode="after")
    def validate_internal_references(self) -> Self:
        """保证步骤、问题和困难引用在一份 Solution 内部闭合。"""
        step_ids = [step.solution_step_id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("Solution step ids must be unique.")

        question_ids = [
            question.question_id
            for step in self.steps
            for question in step.tutor_questions
        ]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("Tutor question ids must be unique.")

        return self


class SolveOutcome(StrictModel):
    """求解后的代码级分支结果；只有 solved 分支可交给 verifier。"""

    schema_version: Literal[1] = 1
    status: Literal["solved", "incomplete", "ambiguous", "unsupported"]
    solution: Solution | None = None
    clarification_questions: list[str] = Field(default_factory=list, max_length=5)
    reason: str = Field(default="", max_length=1_000)

    @model_validator(mode="after")
    def validate_status_payload(self) -> Self:
        if self.status == "solved":
            if self.solution is None:
                raise ValueError("A solved outcome requires a Solution.")
            if self.clarification_questions:
                raise ValueError("A solved outcome cannot request clarification.")
        else:
            if self.solution is not None:
                raise ValueError("An unresolved outcome cannot contain a Solution.")
            if (
                self.status in {"incomplete", "ambiguous"}
                and not self.clarification_questions
            ):
                raise ValueError(
                    "Incomplete and ambiguous outcomes require clarification questions."
                )
        return self


SOLUTION_SCHEMA = Solution.model_json_schema()


def validate_solution(solution: Solution | dict[str, object]) -> Solution:
    """返回通过 Pydantic 校验的 Solution。"""
    if isinstance(solution, Solution):
        return solution
    return Solution.model_validate(solution)
