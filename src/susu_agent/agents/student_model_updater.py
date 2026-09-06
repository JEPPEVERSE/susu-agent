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
    return json.dumps(
        {
            "teaching_state": teaching_state,
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
