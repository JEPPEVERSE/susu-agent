"""数学解题 Agent 的结构化输出模型。"""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """拒绝模型输出 Schema 之外的字段。"""

    model_config = ConfigDict(extra="forbid")


class TutorQuestion(StrictModel):
    """Tutor 在某个解题步骤中可以逐步提出的问题。"""

    question_id: str = Field(pattern=r"^question_[0-9]+$", max_length=100)
    question: str = Field(min_length=1, max_length=1_000)
    teaching_goal: str = Field(min_length=1, max_length=500)
    expected_answer: str = Field(min_length=1, max_length=1_000)
    answer_checkpoints: list[str] = Field(default_factory=list, max_length=10)
    hint_ladder: list[str] = Field(default_factory=list, max_length=4)


class SolutionStep(StrictModel):
    """依照教案形成的一步题目级解决过程。"""

    solution_step_id: str = Field(pattern=r"^step_[0-9]+$", max_length=100)
    lesson_plan_step_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=500)
    derivation: str = Field(
        min_length=1,
        max_length=4_000,
        description="可核验的数学推导摘要，不记录模型的隐藏思维过程。",
    )
    result: str = Field(min_length=1, max_length=2_000)
    knowledge_points: list[str] = Field(default_factory=list, max_length=20)
    tutor_questions: list[TutorQuestion] = Field(default_factory=list, max_length=10)


class LikelyStudentDifficulty(StrictModel):
    """结合题目结构和学生模型预判的潜在困难。"""

    difficulty_id: str = Field(pattern=r"^difficulty_[0-9]+$", max_length=100)
    related_solution_step_ids: list[str] = Field(
        default_factory=list,
        max_length=20,
    )
    description: str = Field(min_length=1, max_length=500)
    evidence_source: Literal["student_model", "problem_structure", "both"]
    likelihood: Literal["low", "medium", "high"]
    tutor_strategy: str = Field(min_length=1, max_length=1_000)


class Solution(StrictModel):
    """一份题目级、教案驱动且供 Tutor 内部使用的解题计划。"""

    schema_version: Literal[1] = 1
    subject: Literal["math"] = "math"
    problem_statement: str = Field(min_length=1, max_length=8_000)
    problem_status: Literal["solvable", "incomplete", "ambiguous", "not_math"]
    clarification_questions: list[str] = Field(default_factory=list, max_length=5)
    goal: str = Field(min_length=1, max_length=1_000)
    known_conditions: list[str] = Field(default_factory=list, max_length=50)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    knowledge_points: list[str] = Field(default_factory=list, max_length=50)
    strategy_summary: str = Field(min_length=1, max_length=2_000)
    steps: list[SolutionStep] = Field(default_factory=list, max_length=30)
    likely_student_difficulties: list[LikelyStudentDifficulty] = Field(
        default_factory=list,
        max_length=30,
    )
    final_answer: str = Field(max_length=4_000)
    verification: list[str] = Field(default_factory=list, max_length=20)

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

        difficulty_ids = [
            difficulty.difficulty_id
            for difficulty in self.likely_student_difficulties
        ]
        if len(difficulty_ids) != len(set(difficulty_ids)):
            raise ValueError("Student difficulty ids must be unique.")

        known_steps = set(step_ids)
        unknown_steps = sorted(
            {
                step_id
                for difficulty in self.likely_student_difficulties
                for step_id in difficulty.related_solution_step_ids
                if step_id not in known_steps
            }
        )
        if unknown_steps:
            raise ValueError(
                "Student difficulties reference unknown Solution steps: "
                f"{unknown_steps!r}."
            )
        return self


SOLUTION_SCHEMA = Solution.model_json_schema()


def validate_solution(solution: Solution | dict[str, object]) -> Solution:
    """返回通过 Pydantic 校验的 Solution。"""
    if isinstance(solution, Solution):
        return solution
    return Solution.model_validate(solution)
