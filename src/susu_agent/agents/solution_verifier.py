"""v0.2 解题图验证 Agent。"""

import json
from dataclasses import dataclass

from agents import Agent, RunContextWrapper

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.model_config import resolve_agent_model, supports_native_structured_output
from susu_agent.schemas.solution import Solution
from susu_agent.schemas.v02 import VerificationReport
from susu_agent.structured_output import build_json_output_instruction


@dataclass(frozen=True, slots=True)
class SolutionVerifierRunContext:
    lesson_plan: LessonPlanBundle


MODEL = resolve_agent_model("SOLUTION_VERIFIER_MODEL")
USES_NATIVE_OUTPUT = supports_native_structured_output(MODEL)


def compose_solution_verifier_instructions(lesson_plan: LessonPlanBundle) -> str:
    instruction = (
        load_instruction("solution_verifier_instruction.md").strip()
        + "\n\n<lesson_plan>\n"
        + lesson_plan.instruction
        + "\n</lesson_plan>"
    )
    if not USES_NATIVE_OUTPUT:
        instruction += build_json_output_instruction(VerificationReport)
    return instruction


def provide_solution_verifier_instructions(
    context: RunContextWrapper[SolutionVerifierRunContext],
    _agent: Agent[SolutionVerifierRunContext],
) -> str:
    return compose_solution_verifier_instructions(context.context.lesson_plan)


def build_solution_verifier_input(problem_statement: str, solution: Solution) -> str:
    return json.dumps(
        {"problem_statement": problem_statement, "solution": solution.model_dump(mode="json")},
        ensure_ascii=False,
        indent=2,
    )


solution_verifier_agent = Agent[SolutionVerifierRunContext](
    name="solution_verifier",
    instructions=provide_solution_verifier_instructions,
    model=MODEL,
    output_type=VerificationReport if USES_NATIVE_OUTPUT else None,
)

