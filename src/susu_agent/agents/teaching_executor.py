"""v0.3 语境化诊断与单轮教学表达 Agent。"""

import json
from dataclasses import asdict
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from agents import Agent, RunContextWrapper

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.context_builder import ContextMessage
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.model_config import resolve_agent_model, supports_native_structured_output
from susu_agent.schemas.v03 import TeachingExecution
from susu_agent.structured_output import build_json_output_instruction
from susu_agent.teaching_runtime import MAX_NODE_ATTEMPTS


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


def build_executor_student_context(
    student_model: Mapping[str, Any],
    teaching_state: Mapping[str, Any],
    current_step: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """投影当轮个性化所需字段，避免重复发送完整六科学习档案。"""
    subject = teaching_state.get("lesson_plan", {}).get("subject")
    identity = student_model.get("identity", {})
    learning_profile = student_model.get("learning_profile", {})
    subject_profile = student_model.get("subjects", {}).get(subject, {})
    knowledge_graph = subject_profile.get("knowledge_graph", {})
    relevant_concept_ids = set(
        current_step.get("concept_ids", []) if current_step is not None else []
    )
    misconceptions = student_model.get("learning_history", {}).get(
        "persistent_misconceptions", []
    )
    return {
        "student_id": student_model.get("student_id"),
        "model_version": student_model.get("model_version"),
        "identity": {
            "display_name": identity.get("display_name"),
            "grade": identity.get("grade", "unknown"),
        },
        "learning_profile": {
            "strength_subjects": learning_profile.get("strength_subjects", []),
            "support_subjects": learning_profile.get("support_subjects", []),
            "learning_styles": learning_profile.get("learning_styles", []),
            "learning_engagement": learning_profile.get(
                "learning_engagement", "unknown"
            ),
            "preferences": learning_profile.get("preferences", {}),
        },
        "current_subject": subject,
        "current_subject_profile": {
            "level": subject_profile.get("level", {}),
            "strengths": subject_profile.get("strengths", []),
            "weaknesses": subject_profile.get("weaknesses", []),
            "knowledge_graph": {
                "nodes": [
                    node
                    for node in knowledge_graph.get("nodes", [])
                    if node.get("concept_id") in relevant_concept_ids
                ]
            },
            "notes": subject_profile.get("notes", ""),
        },
        "relevant_misconceptions": [
            item
            for item in misconceptions
            if item.get("subject") == subject
            and item.get("concept_id") in relevant_concept_ids
        ],
    }


def build_teaching_executor_input(
    current_user_message: str,
    teaching_state: Mapping[str, Any],
    student_model: Mapping[str, Any],
    teacher_model: Mapping[str, Any],
    recent_messages: Sequence[ContextMessage],
    memory_context: Mapping[str, Any] | None = None,
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
    current_step_id = (
        current_node.get("solution_step_id")
        if isinstance(current_node, Mapping)
        else None
    )
    if isinstance(solution, Mapping):
        current_step = next(
            (step for step in solution.get("steps", []) if step.get("solution_step_id") == current_step_id),
            None,
        )
    if isinstance(current_step, Mapping):
        current_step = {
            key: current_step.get(key)
            for key in (
                "solution_step_id",
                "lesson_plan_step_id",
                "title",
                "goal",
                "derivation",
                "result",
                "concept_ids",
            )
        }
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
    available_step_ids = {
        node.get("solution_step_id")
        for node in available_nodes
        if node.get("solution_step_id") is not None
    }
    anticipated_difficulties = [
        item
        for item in (
            strategy.get("anticipated_difficulties", [])
            if isinstance(strategy, Mapping)
            else []
        )
        if set(item.get("related_solution_step_ids", [])) & available_step_ids
    ]
    satisfied_prefix = f"{current_node_id}:checkpoint_"
    satisfied_checkpoint_indices = [
        int(value.removeprefix(satisfied_prefix))
        for value in progress.get("satisfied_checkpoint_ids", [])
        if isinstance(value, str) and value.startswith(satisfied_prefix)
    ]
    attempts = progress.get("attempts_by_node", {}).get(current_node_id, 0)
    hint_index = progress.get("hint_indices_by_node", {}).get(current_node_id, 0)
    return json.dumps(
        {
            "current_user_message": current_user_message,
            "problem_representation": teaching_state.get(
                "problem_representation"
            ),
            "current_teaching_node": current_node,
            "current_solution_step": current_step,
            "available_strategy_nodes": available_nodes,
            "available_solution_questions": available_solution_questions,
            "anticipated_difficulties": anticipated_difficulties,
            "teaching_strategy_summary": strategy.get("summary") if isinstance(strategy, Mapping) else None,
            "completion_criteria": strategy.get("completion_criteria", []) if isinstance(strategy, Mapping) else [],
            "replan_triggers": strategy.get("replan_triggers", []) if isinstance(strategy, Mapping) else [],
            "teaching_progress": progress,
            "runtime_control": {
                "current_node_attempts": attempts,
                "max_node_attempts": MAX_NODE_ATTEMPTS,
                "current_hint_index": hint_index,
                "satisfied_checkpoint_indices": satisfied_checkpoint_indices,
                "force_advance_after_this_answer_if_not_complete": (
                    attempts >= MAX_NODE_ATTEMPTS - 1
                ),
            },
            "active_questions": [
                item for item in teaching_state.get("open_question_history", [])
                if item.get("status") == "open"
            ],
            "student_model": build_executor_student_context(
                student_model, teaching_state, current_step
            ),
            "teacher_model": teacher_model,
            "retrieved_misconception_memory": dict(memory_context or {}),
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
