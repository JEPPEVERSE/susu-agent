"""v0.3 个人模型总结与长期记忆提案 Agent。"""

import json
from typing import Any, Mapping

from agents import Agent

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.model_config import resolve_agent_model, supports_native_structured_output
from susu_agent.schemas.v03 import StudentModelPatch
from susu_agent.structured_output import build_json_output_instruction


MODEL = resolve_agent_model("STUDENT_MODEL_SUMMARIZER_MODEL")
USES_NATIVE_OUTPUT = supports_native_structured_output(MODEL)
INSTRUCTIONS = load_instruction("student_model_summarizer_instruction.md").strip()
if not USES_NATIVE_OUTPUT:
    INSTRUCTIONS += build_json_output_instruction(StudentModelPatch)


def build_student_model_summarizer_input(
    teaching_state: Mapping[str, Any],
    student_model: Mapping[str, Any],
) -> str:
    solution = teaching_state.get("solution") or {}
    progress = teaching_state.get("teaching_progress", {})
    strategy = teaching_state.get("teaching_strategy") or {}
    subject = teaching_state.get("lesson_plan", {}).get("subject")
    misconceptions = student_model.get("learning_history", {}).get(
        "persistent_misconceptions", []
    )
    relevant_concept_ids = {
        concept_id
        for step in solution.get("steps", [])
        for concept_id in step.get("concept_ids", [])
    }
    current_subject_profile = dict(
        student_model.get("subjects", {}).get(subject, {})
    )
    knowledge_graph = current_subject_profile.get("knowledge_graph", {})
    current_subject_profile["knowledge_graph"] = {
        "nodes": [
            node
            for node in knowledge_graph.get("nodes", [])
            if node.get("concept_id") in relevant_concept_ids
        ],
        "edges": [],
    }
    student_model_context = {
        "student_id": student_model.get("student_id"),
        "model_version": student_model.get("model_version", 1),
        "current_subject": subject,
        "current_subject_profile": current_subject_profile,
        "current_subject_misconceptions": [
            item for item in misconceptions if item.get("subject") == subject
        ],
        "meta_knowledge_cards": student_model.get("meta_knowledge_cards", []),
    }
    completed_node_ids = set(progress.get("completed_strategy_node_ids", []))
    completed_solution_step_ids = list(
        dict.fromkeys(
            node.get("solution_step_id")
            for node in strategy.get("nodes", [])
            if node.get("node_id") in completed_node_ids
            and node.get("solution_step_id") is not None
        )
    )
    return json.dumps(
        {
            "subject": subject,
            "solution_outline": {
                "goal": solution.get("goal"),
                "strategy_summary": solution.get("strategy_summary"),
                "steps": [
                    {
                        "solution_step_id": step.get("solution_step_id"),
                        "goal": step.get("goal"),
                        "result": step.get("result"),
                        "concept_ids": step.get("concept_ids", []),
                    }
                    for step in solution.get("steps", [])
                ],
            },
            "teaching_record": {
                "learning_evidence": teaching_state.get("learning_evidence", []),
                "question_history": teaching_state.get(
                    "open_question_history", []
                ),
                "completed_solution_step_ids": completed_solution_step_ids,
                "conversation_summary": teaching_state.get(
                    "conversation_summary", ""
                ),
            },
            "problem_representation": teaching_state.get(
                "problem_representation"
            ),
            "retrieval_cache": teaching_state.get("retrieval_cache", {}),
            "student_model": student_model_context,
            "base_model_version": student_model.get("model_version", 1),
        },
        ensure_ascii=False,
        indent=2,
    )


student_model_summarizer_agent = Agent(
    name="student_model_summarizer",
    instructions=INSTRUCTIONS,
    model=MODEL,
    output_type=StudentModelPatch if USES_NATIVE_OUTPUT else None,
)
