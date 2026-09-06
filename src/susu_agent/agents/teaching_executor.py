"""v0.2 每轮教学执行与表达 Agent。"""

import json
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from agents import Agent, RunContextWrapper

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.context_builder import ContextMessage
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.model_config import resolve_agent_model, supports_native_structured_output
from susu_agent.schemas.v02 import TeachingExecution
from susu_agent.structured_output import build_json_output_instruction


@dataclass(frozen=True, slots=True)
class TeachingExecutorRunContext:
    lesson_plan: LessonPlanBundle


MODEL = resolve_agent_model("TEACHING_EXECUTOR_MODEL")
USES_NATIVE_OUTPUT = supports_native_structured_output(MODEL)


def compose_teaching_executor_instructions(lesson_plan: LessonPlanBundle) -> str:
    instruction = load_instruction("teaching_executor_instruction.md").strip()
    if not USES_NATIVE_OUTPUT:
        instruction += build_json_output_instruction(TeachingExecution)
    return instruction


def provide_teaching_executor_instructions(
    context: RunContextWrapper[TeachingExecutorRunContext],
    _agent: Agent[TeachingExecutorRunContext],
) -> str:
    return compose_teaching_executor_instructions(context.context.lesson_plan)


def build_teaching_executor_input(
    current_user_message: str,
    teaching_state: Mapping[str, Any],
    student_model: Mapping[str, Any],
    teacher_model: Mapping[str, Any],
    recent_messages: Sequence[ContextMessage],
) -> str:
    strategy = teaching_state.get("teaching_strategy")
    progress = teaching_state.get("teaching_progress", {})
    current_node_id = progress.get("current_strategy_node_id") if isinstance(progress, Mapping) else None
    current_node = None
    if isinstance(strategy, Mapping):
        current_node = next(
            (node for node in strategy.get("nodes", []) if node.get("node_id") == current_node_id),
            None,
        )
    solution = teaching_state.get("solution")
    current_step = None
    current_step_id = progress.get("current_solution_step_id") if isinstance(progress, Mapping) else None
    if isinstance(solution, Mapping):
        current_step = next(
            (step for step in solution.get("steps", []) if step.get("solution_step_id") == current_step_id),
            None,
        )
    return json.dumps(
        {
            "current_user_message": current_user_message,
            "current_teaching_node": current_node,
            "current_solution_step": current_step,
            "teaching_strategy_summary": strategy.get("summary") if isinstance(strategy, Mapping) else None,
            "completion_criteria": strategy.get("completion_criteria", []) if isinstance(strategy, Mapping) else [],
            "replan_triggers": strategy.get("replan_triggers", []) if isinstance(strategy, Mapping) else [],
            "teaching_progress": progress,
            "active_questions": [
                item for item in teaching_state.get("open_question_history", [])
                if item.get("status") == "open"
            ],
            "student_model": student_model,
            "teacher_model": teacher_model,
            "recent_messages": [asdict(message) for message in recent_messages[-4:]],
        },
        ensure_ascii=False,
        indent=2,
    )


teaching_executor_agent = Agent[TeachingExecutorRunContext](
    name="teaching_executor",
    instructions=provide_teaching_executor_instructions,
    model=MODEL,
    output_type=TeachingExecution if USES_NATIVE_OUTPUT else None,
)
