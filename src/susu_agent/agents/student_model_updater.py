"""v0.2 低频学生模型总结 Agent。"""

import json
from typing import Any, Mapping

from agents import Agent

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.model_config import resolve_agent_model, supports_native_structured_output
from susu_agent.schemas.v02 import StudentModelPatch
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
    return json.dumps(
        {
            "subject": teaching_state.get("lesson_plan", {}).get("subject"),
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
                "completed_solution_step_ids": progress.get(
                    "completed_solution_step_ids", []
                ),
                "confirmed_steps": progress.get("confirmed_steps", []),
                "rolling_summary": teaching_state.get("memory_meta", {}).get(
                    "rolling_summary", ""
                ),
            },
            "student_model": student_model,
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
