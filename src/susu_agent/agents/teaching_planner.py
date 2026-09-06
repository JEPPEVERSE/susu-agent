"""v0.2 一次性教学策略图规划 Agent。"""

import json
from dataclasses import dataclass
from typing import Any, Mapping

from agents import Agent, RunContextWrapper

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.model_config import resolve_agent_model, supports_native_structured_output
from susu_agent.schemas.solution import Solution
from susu_agent.schemas.v02 import TeachingStrategy, VerificationReport
from susu_agent.structured_output import build_json_output_instruction


@dataclass(frozen=True, slots=True)
class TeachingPlannerRunContext:
    lesson_plan: LessonPlanBundle


MODEL = resolve_agent_model("TEACHING_PLANNER_MODEL")
USES_NATIVE_OUTPUT = supports_native_structured_output(MODEL)


def compose_teaching_planner_instructions(lesson_plan: LessonPlanBundle) -> str:
    instruction = (
        load_instruction("teaching_planner_instruction.md").strip()
        + "\n\n<lesson_plan>\n"
        + lesson_plan.instruction
        + "\n\n"
        + lesson_plan.context
        + "\n</lesson_plan>"
    )
    if not USES_NATIVE_OUTPUT:
        instruction += build_json_output_instruction(TeachingStrategy)
    return instruction


def provide_teaching_planner_instructions(
    context: RunContextWrapper[TeachingPlannerRunContext],
    _agent: Agent[TeachingPlannerRunContext],
) -> str:
    return compose_teaching_planner_instructions(context.context.lesson_plan)


def build_teaching_planner_input(
    solution: Solution,
    verification: VerificationReport,
    student_model: Mapping[str, Any],
    teacher_model: Mapping[str, Any],
    teaching_state: Mapping[str, Any],
) -> str:
    return json.dumps(
        {
            "verified_solution": solution.model_dump(mode="json"),
            "verification_report": verification.model_dump(mode="json"),
            "student_model": student_model,
            "teacher_model": teacher_model,
            "initial_teaching_state": teaching_state,
        },
        ensure_ascii=False,
        indent=2,
    )


teaching_planner_agent = Agent[TeachingPlannerRunContext](
    name="teaching_planner",
    instructions=provide_teaching_planner_instructions,
    model=MODEL,
    output_type=TeachingStrategy if USES_NATIVE_OUTPUT else None,
)

