import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.agents.teaching_state_updater import (
    TeachingStateUpdate,
    apply_teaching_state_update,
)
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository


class TeachingStateUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = TeachingStateRepository.create_initial_state("problem_0")

    def test_incremental_update_is_merged_into_the_full_state(self) -> None:
        updated_state = apply_teaching_state_update(
            self.state,
            TeachingStateUpdate(
                stage="recall_knowledge",
                confirmed_steps_to_add=["identified_known_conditions"],
                misconceptions_to_add=["confuses_domain_and_range"],
                open_question="函数的定义域需要满足什么条件？",
                next_teacher_action="ask_question",
                rolling_summary="学生已识别题目条件，需要回忆定义域限制。",
            ),
        )

        self.assertEqual(updated_state["teaching_progress"]["stage"], "recall_knowledge")
        self.assertIn(
            "identified_known_conditions",
            updated_state["teaching_progress"]["confirmed_steps"],
        )
        self.assertIn(
            "confuses_domain_and_range",
            updated_state["student_model"]["status"]["main_misconceptions"],
        )
        self.assertEqual(updated_state["open_question_history"][0]["status"], "open")
        self.assertEqual(
            updated_state["memory_meta"]["rolling_summary"],
            "学生已识别题目条件，需要回忆定义域限制。",
        )
