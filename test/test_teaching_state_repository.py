import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.repositories.teaching_state_repository import TeachingStateRepository


def make_v6_state(session_id: str) -> dict[str, object]:
    state = TeachingStateRepository.create_initial_state(session_id)
    state["schema_version"] = 6
    state["teaching_progress"] = {
        "current_strategy_node_id": None,
        "stage": "understand_task",
        "current_lesson_plan_step_id": None,
        "completed_lesson_plan_step_ids": [],
        "lesson_plan_step_summary": "",
        "current_solution_step_id": None,
        "completed_solution_step_ids": [],
        "solution_step_summary": "",
        "current_solution_question_id": None,
        "completed_solution_question_ids": [],
        "hints_num": 0,
        "confirmed_steps": [],
        "next_teacher_action": "ask_question",
    }
    state["student_model"] = {"status": {}}
    state["memory_meta"] = {
        "last_processed_message_id": None,
        "last_compacted_message_id": None,
        "rolling_summary": "",
    }
    state.pop("conversation_summary", None)
    return state


class TeachingStateRepositoryTests(unittest.TestCase):
    def test_version_six_strategy_is_invalidated_for_runtime_replanning(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            db_path = Path(temp_directory) / "state.db"
            repository = TeachingStateRepository(db_path)
            legacy_state = make_v6_state("problem_6")
            legacy_state["teaching_strategy"] = {
                "nodes": [{"node_id": "teach_0"}]
            }
            legacy_state["teaching_progress"]["current_strategy_node_id"] = "teach_0"
            with closing(sqlite3.connect(db_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO teaching_states (
                            session_id, schema_version, state_json, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            "problem_6",
                            6,
                            json.dumps(legacy_state, ensure_ascii=False),
                            legacy_state["updated_at"],
                        ),
                    )

            migrated = repository.get("problem_6")

        self.assertIsNone(migrated["teaching_strategy"])
        self.assertIsNone(
            migrated["teaching_progress"]["current_strategy_node_id"]
        )
        self.assertNotIn("student_model", migrated)

    def test_version_five_solution_is_migrated_to_the_narrow_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            db_path = Path(temp_directory) / "state.db"
            repository = TeachingStateRepository(db_path)
            legacy_state = TeachingStateRepository.create_initial_state("problem_5")
            legacy_state["schema_version"] = 5
            legacy_state["original_problem"] = {"problem_statement": "测试题"}
            legacy_state["solution"] = {
                "schema_version": 1,
                "subject": "math",
                "problem_statement": "测试题",
                "problem_status": "solvable",
                "clarification_questions": [],
                "goal": "完成测试题",
                "known_conditions": [],
                "assumptions": [],
                "knowledge_points": ["旧知识点"],
                "strategy_summary": "直接求解。",
                "steps": [
                    {
                        "solution_step_id": "step_0",
                        "lesson_plan_step_id": "S1",
                        "title": "明确目标",
                        "goal": "明确目标",
                        "derivation": "题目目标明确。",
                        "result": "完成目标识别。",
                        "knowledge_points": ["旧知识点"],
                        "tutor_questions": [],
                    }
                ],
                "likely_student_difficulties": [],
                "final_answer": "测试答案",
                "verification": [],
            }
            legacy_state["verification_report"] = {
                "schema_version": 1,
                "verdict": "passed",
                "summary": "验证通过。",
                "checked_solution_step_ids": ["step_0"],
                "issues": [],
                "confidence": "high",
            }

            with closing(sqlite3.connect(db_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO teaching_states (
                            session_id, schema_version, state_json, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            "problem_5",
                            5,
                            json.dumps(legacy_state, ensure_ascii=False),
                            legacy_state["updated_at"],
                        ),
                    )

            migrated = repository.get("problem_5")

        self.assertEqual(migrated["schema_version"], 7)
        self.assertEqual(migrated["original_problem"]["status"], "solved")
        self.assertEqual(migrated["solution"]["schema_version"], 2)
        self.assertNotIn("subject", migrated["solution"])
        self.assertNotIn("problem_status", migrated["solution"])
        self.assertNotIn("likely_student_difficulties", migrated["solution"])
        self.assertEqual(migrated["solution"]["steps"][0]["concept_ids"], [])
        self.assertIsNone(migrated["verification_report"])
        self.assertIsNone(migrated["teaching_strategy"])
        self.assertNotIn("student_model", migrated)

    def test_get_or_create_persists_an_initial_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = TeachingStateRepository(Path(temp_directory) / "state.db")
            created_state = repository.get_or_create("problem_0")
            stored_state = repository.get("problem_0")

        self.assertEqual(created_state["session_id"], "problem_0")
        self.assertEqual(created_state["schema_version"], 7)
        self.assertIsNone(created_state["solution"])
        self.assertNotIn("student_model", created_state)
        self.assertNotIn("current_solution_step_id", created_state["teaching_progress"])
        self.assertEqual(created_state["lesson_plan"]["subject"], "math")
        self.assertEqual(
            created_state["lesson_plan"]["lesson_plan_version"],
            "3.0.0",
        )
        self.assertEqual(
            created_state["lesson_plan"]["step_ids"],
            [f"S{i}" for i in range(1, 10)],
        )
        self.assertEqual(
            created_state["lesson_plan"]["instruction_sources"],
            ["math/instruction.md"],
        )
        self.assertEqual(len(created_state["lesson_plan"]["content_digest"]), 64)
        self.assertNotIn("stage", created_state["teaching_progress"])
        self.assertEqual(stored_state, created_state)

    def test_version_one_state_is_migrated_to_lesson_plan_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            db_path = Path(temp_directory) / "state.db"
            repository = TeachingStateRepository(db_path)
            legacy_state = make_v6_state("problem_1")
            legacy_state["schema_version"] = 1
            legacy_state.pop("lesson_plan")
            progress = legacy_state["teaching_progress"]
            progress["stage"] = "solve"
            progress.pop("current_lesson_plan_step_id")
            progress.pop("completed_lesson_plan_step_ids")
            progress.pop("lesson_plan_step_summary")

            with closing(sqlite3.connect(db_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO teaching_states (
                            session_id, schema_version, state_json, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            "problem_1",
                            1,
                            json.dumps(legacy_state, ensure_ascii=False),
                            legacy_state["updated_at"],
                        ),
                    )

            migrated_state = repository.get("problem_1")

        self.assertIsNotNone(migrated_state)
        self.assertEqual(migrated_state["schema_version"], 7)
        self.assertEqual(migrated_state["lesson_plan"]["subject"], "math")
        self.assertNotIn("stage", migrated_state["teaching_progress"])
        self.assertNotIn(
            "current_lesson_plan_step_id", migrated_state["teaching_progress"]
        )
        self.assertIsNone(migrated_state["solution"])

    def test_version_two_step_labels_are_migrated_to_step_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            db_path = Path(temp_directory) / "state.db"
            repository = TeachingStateRepository(db_path)
            legacy_state = make_v6_state("problem_2")
            legacy_state["schema_version"] = 2
            legacy_state["lesson_plan"].pop("lesson_plan_version")
            legacy_state["lesson_plan"].pop("step_ids")
            progress = legacy_state["teaching_progress"]
            progress["current_lesson_plan_step"] = "S2 提取条件与合法边界"
            progress["completed_lesson_plan_steps"] = [
                "S1 明确研究对象与交付目标"
            ]
            progress.pop("current_lesson_plan_step_id")
            progress.pop("completed_lesson_plan_step_ids")

            with closing(sqlite3.connect(db_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO teaching_states (
                            session_id, schema_version, state_json, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            "problem_2",
                            2,
                            json.dumps(legacy_state, ensure_ascii=False),
                            legacy_state["updated_at"],
                        ),
                    )

            migrated_state = repository.get("problem_2")

        self.assertEqual(migrated_state["schema_version"], 7)
        self.assertNotIn("current_lesson_plan_step_id", migrated_state["teaching_progress"])

    def test_version_three_state_receives_solution_execution_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            db_path = Path(temp_directory) / "state.db"
            repository = TeachingStateRepository(db_path)
            legacy_state = make_v6_state("problem_3")
            legacy_state["schema_version"] = 3
            legacy_state.pop("solution")
            progress = legacy_state["teaching_progress"]
            progress.pop("current_solution_step_id")
            progress.pop("completed_solution_step_ids")
            progress.pop("solution_step_summary")
            progress.pop("current_solution_question_id")
            progress.pop("completed_solution_question_ids")

            with closing(sqlite3.connect(db_path)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO teaching_states (
                            session_id, schema_version, state_json, updated_at
                        ) VALUES (?, ?, ?, ?)
                        """,
                        (
                            "problem_3",
                            3,
                            json.dumps(legacy_state, ensure_ascii=False),
                            legacy_state["updated_at"],
                        ),
                    )

            migrated_state = repository.get("problem_3")

        self.assertEqual(migrated_state["schema_version"], 7)
        self.assertIsNone(migrated_state["solution"])
        self.assertEqual(
            migrated_state["teaching_progress"]["completed_strategy_node_ids"], []
        )


if __name__ == "__main__":
    unittest.main()
