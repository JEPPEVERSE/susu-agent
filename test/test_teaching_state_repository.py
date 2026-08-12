import sys
import tempfile
import unittest
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
        self.assertEqual(
            created_state["teaching_progress"]["stage"],
            "understand_problem",
        )
        self.assertEqual(stored_state, created_state)


if __name__ == "__main__":
    unittest.main()
