import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.schemas.v02 import ExecutionStateDelta, TeachingExecution
from susu_agent.structured_output import (
    build_json_output_instruction,
    parse_structured_output,
)


class StructuredOutputCompatibilityTests(unittest.TestCase):
    def test_parses_plain_json_text(self) -> None:
        output = json.dumps(
            {
                "conversation_summary": "学生正在识别目标。",
            }
        )

        parsed = parse_structured_output(output, ExecutionStateDelta)

        self.assertEqual(parsed.conversation_summary, "学生正在识别目标。")

    def test_tolerates_json_code_fence(self) -> None:
        output = """```json
{"conversation_summary": null}
```"""

        parsed = parse_structured_output(output, ExecutionStateDelta)

        self.assertIsNone(parsed.conversation_summary)

    def test_native_pydantic_output_passes_through(self) -> None:
        output = ExecutionStateDelta(conversation_summary="待验证。")

        self.assertIs(
            parse_structured_output(output, ExecutionStateDelta),
            output,
        )

    def test_instruction_contains_schema_and_json_only_rule(self) -> None:
        instruction = build_json_output_instruction(TeachingExecution)

        self.assertIn("只返回一个合法的 JSON object", instruction)
        self.assertIn('"answered_open_question_feedback"', instruction)


if __name__ == "__main__":
    unittest.main()
