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
from susu_agent.agents.teaching_state_updater import (
    TEACHING_STATE_UPDATER_USES_NATIVE_OUTPUT,
    TeachingStateUpdate,
    teaching_state_updater,
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
        self.assertIn("current_solution_question_id", instruction)

    def test_dynamic_instruction_uses_runtime_lesson_plan(self) -> None:
        lesson_plan = load_lesson_plan("math")
        run_context = SimpleNamespace(
            context=TutorRunContext(lesson_plan=lesson_plan)
        )

        instruction = provide_tutor_instructions(run_context, tutor_agent)

        self.assertIn('subject="math"', instruction)
        self.assertIn('version="0.1.0"', instruction)
        self.assertIn("- S1: 明确研究对象与交付目标", instruction)

    def test_updater_reads_its_markdown_instruction(self) -> None:
        instruction = load_instruction("teaching_state_updater_instruction.md")

        self.assertIn("# 教学状态更新器", instruction)
        self.assertTrue(teaching_state_updater.instructions.startswith(instruction))
        if TEACHING_STATE_UPDATER_USES_NATIVE_OUTPUT:
            self.assertIs(
                teaching_state_updater.output_type,
                TeachingStateUpdate,
            )
        else:
            self.assertIsNone(teaching_state_updater.output_type)
            self.assertIn(
                "## JSON 文本兼容模式",
                teaching_state_updater.instructions,
            )


if __name__ == "__main__":
    unittest.main()
