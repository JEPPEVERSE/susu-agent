import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.agents.tutor import (
    compose_tutor_instructions,
    provide_tutor_instructions,
    TutorRunContext,
    tutor_agent,
)
from susu_agent.lesson_plan_loader import load_lesson_plan


class InstructionLoadingTests(unittest.TestCase):
    def test_tutor_combines_general_rules_and_selected_lesson_plan(self) -> None:
        lesson_plan = load_lesson_plan("math")
        instruction = compose_tutor_instructions(lesson_plan)

        self.assertIn("# 通用启发式 Tutor Agent Instruction", instruction)
        self.assertIn('<lesson_plan_instruction subject="math"', instruction)
        self.assertIn("S1 明确研究对象与交付目标", instruction)
        self.assertIs(tutor_agent.instructions, provide_tutor_instructions)

    def test_general_tutor_instruction_is_not_bound_to_math(self) -> None:
        instruction = load_instruction("tutor_instruction.md")

        self.assertIn("跨学科 Tutor", instruction)
        self.assertNotIn("高中数学教师", instruction)
        self.assertIn("后台解题 Agent", instruction)
        self.assertIn("current_strategy_node_id", instruction)

    def test_dynamic_instruction_uses_runtime_lesson_plan(self) -> None:
        lesson_plan = load_lesson_plan("math")
        run_context = SimpleNamespace(
            context=TutorRunContext(lesson_plan=lesson_plan)
        )

        instruction = provide_tutor_instructions(run_context, tutor_agent)

        self.assertIn('subject="math"', instruction)
        self.assertIn('version="3.1.1"', instruction)
        self.assertIn("- S1: 明确研究对象与交付目标", instruction)

if __name__ == "__main__":
    unittest.main()
