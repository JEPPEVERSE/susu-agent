import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.repositories.teaching_state_repository import TeachingStateRepository


class TeachingStateRepositoryTests(unittest.TestCase):
    def test_get_or_create_persists_an_initial_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = TeachingStateRepository(Path(temp_directory) / "state.db")
            created_state = repository.get_or_create("problem_0")
            stored_state = repository.get("problem_0")

        self.assertEqual(created_state["session_id"], "problem_0")
        self.assertEqual(created_state["schema_version"], 3)
        self.assertEqual(created_state["lesson_plan"]["subject"], "math")
        self.assertEqual(
            created_state["lesson_plan"]["lesson_plan_version"],
            "0.1.0",
        )
        self.assertEqual(
            created_state["lesson_plan"]["step_ids"],
            [f"S{i}" for i in range(1, 10)],
        )
        self.assertEqual(
            created_state["lesson_plan"]["instruction_sources"],
            ["math/math_tutor_core.md"],
        )
        self.assertEqual(len(created_state["lesson_plan"]["content_digest"]), 64)
        self.assertEqual(
            created_state["teaching_progress"]["stage"],
            "understand_task",
        )
        self.assertEqual(stored_state, created_state)

    def test_version_one_state_is_migrated_to_lesson_plan_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            db_path = Path(temp_directory) / "state.db"
            repository = TeachingStateRepository(db_path)
            legacy_state = TeachingStateRepository.create_initial_state("problem_1")
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
        self.assertEqual(migrated_state["schema_version"], 3)
        self.assertEqual(migrated_state["lesson_plan"]["subject"], "math")
        self.assertEqual(
            migrated_state["teaching_progress"]["stage"],
            "execute",
        )
        self.assertIsNone(
            migrated_state["teaching_progress"]["current_lesson_plan_step_id"]
        )

    def test_version_two_step_labels_are_migrated_to_step_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            db_path = Path(temp_directory) / "state.db"
            repository = TeachingStateRepository(db_path)
            legacy_state = TeachingStateRepository.create_initial_state("problem_2")
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

        self.assertEqual(
            migrated_state["teaching_progress"]["current_lesson_plan_step_id"],
            "S2",
        )
        self.assertEqual(
            migrated_state["teaching_progress"]["completed_lesson_plan_step_ids"],
            ["S1"],
        )


if __name__ == "__main__":
    unittest.main()
