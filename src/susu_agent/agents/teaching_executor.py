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
    reachable_node_ids = {current_node_id}
    if isinstance(current_node, Mapping):
        reachable_node_ids.update(
            transition.get("next_node_id")
            for transition in current_node.get("transitions", [])
            if transition.get("next_node_id") is not None
        )
    available_nodes = []
    if isinstance(strategy, Mapping):
        available_nodes = [
            node
            for node in strategy.get("nodes", [])
            if node.get("node_id") in reachable_node_ids
        ]
    solution = teaching_state.get("solution")
    current_step = None
    current_step_id = progress.get("current_solution_step_id") if isinstance(progress, Mapping) else None
    if isinstance(solution, Mapping):
        current_step = next(
            (step for step in solution.get("steps", []) if step.get("solution_step_id") == current_step_id),
            None,
        )
    available_question_ids = {
        node.get("solution_question_id")
        for node in available_nodes
        if node.get("solution_question_id") is not None
    }
    available_solution_questions = [
        {
            **question,
            "solution_step_id": step.get("solution_step_id"),
        }
        for step in (solution.get("steps", []) if isinstance(solution, Mapping) else [])
        for question in step.get("tutor_questions", [])
        if question.get("question_id") in available_question_ids
    ]
    return json.dumps(
        {
            "current_user_message": current_user_message,
            "current_teaching_node": current_node,
            "current_solution_step": current_step,
            "available_strategy_nodes": available_nodes,
            "available_solution_questions": available_solution_questions,
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
