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
                open_question="What condition must the denominator satisfy?",
                next_teacher_action="ask_question",
                rolling_summary="The student needs to recall denominator restrictions.",
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

    def test_confirmed_steps_allow_a_chinese_teaching_description(self) -> None:
        updated_state = apply_teaching_state_update(
            self.state,
            TeachingStateUpdate(
                confirmed_steps_to_add=["学生识别出已知条件是 x+y=2"],
            ),
        )

        self.assertEqual(
            updated_state["teaching_progress"]["confirmed_steps"],
            ["学生识别出已知条件是 x+y=2"],
        )

    def test_student_answer_is_recorded_against_the_open_question(self) -> None:
        state_with_question = apply_teaching_state_update(
            self.state,
            TeachingStateUpdate(open_question="What condition must the denominator satisfy?"),
        )

        updated_state = apply_teaching_state_update(
            state_with_question,
            TeachingStateUpdate(
                answered_open_question_summary="The student said the denominator cannot be zero.",
                answered_open_question_understanding="correct",
                answered_open_question_assessment="The answer states the required restriction.",
            ),
        )

        question = updated_state["open_question_history"][0]
        self.assertEqual(question["status"], "answered")
        self.assertEqual(
            question["student_answer_summary"],
            "The student said the denominator cannot be zero.",
        )
        self.assertEqual(question["agent_assessment"]["understanding"], "correct")
        self.assertIsNotNone(question["resolved_at"])
        self.assertIsNone(updated_state["teaching_progress"]["open_question"])

    def test_partial_answer_fields_are_rejected(self) -> None:
        state_with_question = apply_teaching_state_update(
            self.state,
            TeachingStateUpdate(open_question="What condition must the denominator satisfy?"),
        )

        with self.assertRaises(ValueError):
            apply_teaching_state_update(
                state_with_question,
                TeachingStateUpdate(
                    answered_open_question_summary="The student is unsure.",
                ),
            )


if __name__ == "__main__":
    unittest.main()
