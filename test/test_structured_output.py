import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.agents.teaching_state_updater import TeachingStateUpdate
from susu_agent.structured_output import (
    build_json_output_instruction,
    parse_structured_output,
)


class StructuredOutputCompatibilityTests(unittest.TestCase):
    def test_parses_plain_json_text(self) -> None:
        output = json.dumps(
            {
                "stage": "execute",
                "confirmed_steps_to_add": [],
                "misconceptions_to_add": [],
            }
        )

        parsed = parse_structured_output(output, TeachingStateUpdate)

        self.assertEqual(parsed.stage, "execute")

    def test_tolerates_json_code_fence(self) -> None:
        output = """```json
{"stage": null, "confirmed_steps_to_add": [], "misconceptions_to_add": []}
```"""

        parsed = parse_structured_output(output, TeachingStateUpdate)

        self.assertIsNone(parsed.stage)

    def test_native_pydantic_output_passes_through(self) -> None:
        output = TeachingStateUpdate(stage="verify")

        self.assertIs(
            parse_structured_output(output, TeachingStateUpdate),
            output,
        )

    def test_instruction_contains_schema_and_json_only_rule(self) -> None:
        instruction = build_json_output_instruction(TeachingStateUpdate)

        self.assertIn("只返回一个合法的 JSON object", instruction)
        self.assertIn('"answered_open_question_summary"', instruction)


if __name__ == "__main__":
    unittest.main()
