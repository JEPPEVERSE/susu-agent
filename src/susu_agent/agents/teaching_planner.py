"""v0.3 记忆增强的一次性教学策略图规划 Agent。"""

import json
import os
from dataclasses import dataclass
from typing import Any, Mapping

from agents import Agent, RunContextWrapper

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.model_config import resolve_agent_model, supports_native_structured_output
from susu_agent.schemas.solution import Solution
from susu_agent.schemas.v03 import TeachingStrategy, VerificationReport
from susu_agent.structured_output import build_json_output_instruction


@dataclass(frozen=True, slots=True)
class TeachingPlannerRunContext:
    lesson_plan: LessonPlanBundle


MODEL = resolve_agent_model("TEACHING_PLANNER_MODEL")
USES_NATIVE_OUTPUT = supports_native_structured_output(MODEL)
QUESTION_DIFFICULTY_ORDER = {"foundation": 0, "standard": 1, "advanced": 2}
MINIMUM_DIFFICULTY_BY_LEVEL = {
    "unassessed": "standard",
    "foundation": "foundation",
    "developing": "standard",
    "proficient": "standard",
    "advanced": "advanced",
}


def build_subject_level_policy(
    solution: Solution,
    student_model: Mapping[str, Any],
    subject: str,
) -> dict[str, Any]:
    """将学科水平 FSM 映射为可由代码强制执行的提问入口。"""
    subject_profile = student_model.get("subjects", {}).get(subject, {})
    level = subject_profile.get("level", {})
    recorded_level_state = level.get("state", "unassessed")
    level_confidence = level.get("confidence", "low")
    effective_level_state = (
        recorded_level_state if level_confidence in {"medium", "high"} else "unassessed"
    )
    minimum_difficulty = MINIMUM_DIFFICULTY_BY_LEVEL.get(
        effective_level_state, "foundation"
    )
    threshold = QUESTION_DIFFICULTY_ORDER[minimum_difficulty]
    questions = [
        (step.solution_step_id, question)
        for step in solution.steps
        for question in step.tutor_questions
    ]
    eligible = [
        (step_id, question)
        for step_id, question in questions
        if QUESTION_DIFFICULTY_ORDER[question.difficulty] >= threshold
    ]
    fallback_used = False
    if not eligible and questions:
        fallback_used = True
        hardest = max(
            QUESTION_DIFFICULTY_ORDER[question.difficulty]
            for _, question in questions
        )
        eligible = [
            (step_id, question)
            for step_id, question in questions
            if QUESTION_DIFFICULTY_ORDER[question.difficulty] == hardest
        ]
    entry_step_id, entry_question = eligible[0] if eligible else (
        solution.steps[0].solution_step_id if solution.steps else None,
        None,
    )
    return {
        "subject": subject,
        "recorded_level_state": recorded_level_state,
        "effective_level_state": effective_level_state,
        "level_confidence": level_confidence,
        "minimum_question_difficulty": minimum_difficulty,
        "skip_foundation_questions": threshold > 0,
        "eligible_question_ids": [question.question_id for _, question in eligible],
        "deferred_question_ids": [
            question.question_id
            for _, question in questions
            if question.question_id
            not in {eligible_question.question_id for _, eligible_question in eligible}
        ],
        "recommended_entry_solution_step_id": entry_step_id,
        "recommended_entry_question_id": (
            entry_question.question_id if entry_question is not None else None
        ),
        "fallback_to_hardest_available": fallback_used,
    }


def compose_teaching_planner_instructions(lesson_plan: LessonPlanBundle) -> str:
    lesson_context = lesson_plan.context
    if os.getenv("MEMORY_ENABLED", "false").casefold() in {"1", "true", "yes", "on"}:
        lesson_context = "\n\n".join(
            lesson_plan.context_sections[heading][1]
            for heading in lesson_plan.always_include_context_headings
        )
    instruction = (
        load_instruction("teaching_planner_instruction.md").strip()
        + "\n\n<lesson_plan>\n"
        + lesson_plan.instruction
        + "\n\n"
        + lesson_context
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
    subject_level_policy: Mapping[str, Any] | None = None,
    memory_context: Mapping[str, Any] | None = None,
) -> str:
    progress = teaching_state.get("teaching_progress", {})
    subject = teaching_state.get("lesson_plan", {}).get("subject", "math")
    policy = dict(
        subject_level_policy
        or build_subject_level_policy(solution, student_model, subject)
    )
    solution_payload = solution.model_dump(mode="json")
    score_history = student_model.get("academic_records", {}).get(
        "score_history", []
    )
    relevant_concept_ids = {
        concept_id for step in solution.steps for concept_id in step.concept_ids
    }
    current_subject_profile = dict(
        student_model.get("subjects", {}).get(subject, {})
    )
    knowledge_graph = current_subject_profile.get("knowledge_graph", {})
    relevant_nodes = [
        node
        for node in knowledge_graph.get("nodes", [])
        if node.get("concept_id") in relevant_concept_ids
    ]
    relevant_node_ids = {node.get("concept_id") for node in relevant_nodes}
    current_subject_profile["knowledge_graph"] = {
        "nodes": relevant_nodes,
        "edges": [
            edge
            for edge in knowledge_graph.get("edges", [])
            if edge.get("source_concept_id") in relevant_node_ids
            and edge.get("target_concept_id") in relevant_node_ids
        ],
    }
    student_model_context = {
        "student_id": student_model.get("student_id"),
        "model_version": student_model.get("model_version"),
        "identity": {
            "display_name": student_model.get("identity", {}).get("display_name"),
            "grade": student_model.get("identity", {}).get("grade", "unknown"),
        },
        "learning_profile": student_model.get("learning_profile", {}),
        "current_subject": subject,
        "current_subject_profile": current_subject_profile,
        "recent_subject_scores": [
            item for item in score_history if item.get("subject") == subject
        ][-5:],
        "education_goals": student_model.get("education_goals", {}),
    }
    return json.dumps(
        {
            "verified_solution": solution_payload,
            "problem_representation": teaching_state.get(
                "problem_representation"
            ),
            "verification_report": verification.model_dump(mode="json"),
            "student_model": student_model_context,
            "teacher_model": teacher_model,
            "subject_level_policy": policy,
            "initial_teaching_state": {
                "problem_status": teaching_state.get("original_problem", {}).get(
                    "status"
                ),
                "teaching_progress": progress,
                "learning_evidence": teaching_state.get("learning_evidence", []),
            },
            "retrieved_teaching_memory": dict(memory_context or {}),
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
