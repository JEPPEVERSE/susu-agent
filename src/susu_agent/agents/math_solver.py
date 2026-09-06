"""根据数学教案生成题目级结构化 Solution。"""

import json
from dataclasses import dataclass
from typing import Any, Mapping

from agents import Agent, RunContextWrapper

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.model_config import (
    resolve_agent_model,
    supports_native_structured_output,
)
from susu_agent.schemas.solution import Solution
from susu_agent.structured_output import build_json_output_instruction


@dataclass(frozen=True, slots=True)
class MathSolverRunContext:
    """数学解题 Agent 单次运行所使用的教案快照。"""

    lesson_plan: LessonPlanBundle


MATH_SOLUTION_MODEL = resolve_agent_model("MATH_SOLUTION_MODEL")
MATH_SOLUTION_USES_NATIVE_OUTPUT = supports_native_structured_output(
    MATH_SOLUTION_MODEL
)


def compose_math_solver_instructions(lesson_plan: LessonPlanBundle) -> str:
    """把解题 Agent 通用规则和完整数学教案组合起来。"""
    base_instruction = load_instruction("math_solver_instruction.md").strip()
    step_catalog = "\n".join(
        f"- {step.step_id}: {step.name}" for step in lesson_plan.steps
    )
    instruction = (
        f"{base_instruction}\n\n"
        f"<lesson_plan subject=\"{lesson_plan.subject}\" "
        f"version=\"{lesson_plan.lesson_plan_version}\">\n"
        "## 允许引用的教案步骤\n\n"
        f"{step_catalog}\n\n"
        "## 教案执行规则\n\n"
        f"{lesson_plan.instruction}\n\n"
        "## 教案理论正文\n\n"
        f"{lesson_plan.context}\n"
        "</lesson_plan>"
    )
    if not MATH_SOLUTION_USES_NATIVE_OUTPUT:
        instruction += build_json_output_instruction(Solution)
    return instruction


def provide_math_solver_instructions(
    context: RunContextWrapper[MathSolverRunContext],
    _agent: Agent[MathSolverRunContext],
) -> str:
    return compose_math_solver_instructions(context.context.lesson_plan)


def build_math_solver_input(
    problem_statement: str,
    student_model: Mapping[str, Any] | None = None,
    revision_context: Mapping[str, Any] | None = None,
) -> str:
    """构造学生无关的标准求解输入。

    ``student_model`` 仅为兼容 v0.1 调用方保留，不进入求解上下文。
    个性化判断由 v0.2 教学规划层负责。
    """
    return json.dumps(
        {
            "problem_statement": problem_statement,
            "revision_context": revision_context,
        },
        ensure_ascii=False,
        indent=2,
    )


def validate_solution_lesson_plan_references(
    solution: Solution,
    lesson_plan: LessonPlanBundle,
) -> None:
    """确保 Solution 只引用当前教案和自身存在的步骤。"""
    if solution.subject != lesson_plan.subject:
        raise ValueError("Solution subject does not match the lesson plan.")

    allowed_lesson_plan_steps = set(lesson_plan.step_ids)
    unknown_lesson_plan_steps = sorted(
        {
            step.lesson_plan_step_id
            for step in solution.steps
            if step.lesson_plan_step_id not in allowed_lesson_plan_steps
        }
    )
    if unknown_lesson_plan_steps:
        raise ValueError(
            "Solution references unknown lesson plan steps: "
            f"{unknown_lesson_plan_steps!r}."
        )

    solution_step_ids = [step.solution_step_id for step in solution.steps]
    if len(solution_step_ids) != len(set(solution_step_ids)):
        raise ValueError("Solution step ids must be unique.")

    question_ids = [
        question.question_id
        for step in solution.steps
        for question in step.tutor_questions
    ]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("Tutor question ids must be unique within a Solution.")

    known_solution_steps = set(solution_step_ids)
    unknown_difficulty_steps = sorted(
        {
            step_id
            for difficulty in solution.likely_student_difficulties
            for step_id in difficulty.related_solution_step_ids
            if step_id not in known_solution_steps
        }
    )
    if unknown_difficulty_steps:
        raise ValueError(
            "Student difficulties reference unknown Solution steps: "
            f"{unknown_difficulty_steps!r}."
        )


math_solution_agent = Agent[MathSolverRunContext](
    name="solution_agent",
    instructions=provide_math_solver_instructions,
    model=MATH_SOLUTION_MODEL,
    output_type=Solution if MATH_SOLUTION_USES_NATIVE_OUTPUT else None,
)
