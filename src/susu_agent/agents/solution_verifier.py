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
    instruction = load_instruction("solution_verifier_instruction.md").strip()
    if not USES_NATIVE_OUTPUT:
        instruction += build_json_output_instruction(VerificationReport)
    return instruction


def provide_solution_verifier_instructions(
    context: RunContextWrapper[SolutionVerifierRunContext],
    _agent: Agent[SolutionVerifierRunContext],
) -> str:
    return compose_solution_verifier_instructions(context.context.lesson_plan)


def build_solution_verifier_input(
    problem_statement: str,
    solution: Solution,
    lesson_plan: LessonPlanBundle,
) -> str:
    referenced_step_ids = tuple(
        dict.fromkeys(step.lesson_plan_step_id for step in solution.steps)
    )
    relevant_headings = tuple(
        dict.fromkeys(
            (
                *lesson_plan.always_include_context_headings,
                *(
                    heading
                    for step_id in referenced_step_ids
                    for heading in lesson_plan.get_step(step_id).context_headings
                ),
            )
        )
    )
    relevant_context = [
        {
            "heading": heading,
            "content": lesson_plan.context_sections[heading][1],
        }
        for heading in relevant_headings
    ]
    solution_projection = {
        "goal": solution.goal,
        "known_conditions": solution.known_conditions,
        "assumptions": solution.assumptions,
        "strategy_summary": solution.strategy_summary,
        "steps": [
            {
                "solution_step_id": step.solution_step_id,
                "lesson_plan_step_id": step.lesson_plan_step_id,
                "title": step.title,
                "goal": step.goal,
                "derivation": step.derivation,
                "result": step.result,
            }
            for step in solution.steps
        ],
        "final_answer": solution.final_answer,
        "verification": solution.verification,
    }
    return json.dumps(
        {
            "origin_problem": problem_statement,
            "solution": solution_projection,
            "lesson_plan": {
                "subject": lesson_plan.subject,
                "referenced_steps": [
                    {"id": step.step_id, "name": step.name}
                    for step in lesson_plan.steps
                    if step.step_id in referenced_step_ids
                ],
                "relevant_context_sections": relevant_context,
            },
        },
        ensure_ascii=False,
        indent=2,
    )


solution_verifier_agent = Agent[SolutionVerifierRunContext](
    name="solution_verifier",
    instructions=provide_solution_verifier_instructions,
    model=MODEL,
    output_type=VerificationReport if USES_NATIVE_OUTPUT else None,
)
