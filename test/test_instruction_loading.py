import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.agents.teaching_state_updater import (
    TeachingStateUpdate,
    teaching_state_updater,
)


class InstructionLoadingTests(unittest.TestCase):
    def test_updater_reads_its_markdown_instruction(self) -> None:
        instruction = load_instruction("teaching_state_updater_instruction.md")

        self.assertIn("# 教学状态更新器", instruction)
        self.assertEqual(teaching_state_updater.instructions, instruction)
        self.assertIs(teaching_state_updater.output_type, TeachingStateUpdate)


if __name__ == "__main__":
    unittest.main()
