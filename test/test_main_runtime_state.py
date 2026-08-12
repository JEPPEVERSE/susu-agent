import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from main import print_current_runtime_state, update_teaching_state
from susu_agent.agents.teaching_state_updater import TeachingStateUpdate
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository


class StubSessionManager:
    current_session_id = "problem_42"


class StubTeachingStateRepository:
    def get_or_create(self, session_id: str) -> dict[str, object]:
        return {"session_id": session_id, "schema_version": 1}


class StatefulTeachingStateRepository:
    def __init__(self) -> None:
        self.state = TeachingStateRepository.create_initial_state("problem_42")
        self.saved_state: dict[str, object] | None = None

    def get_or_create(self, session_id: str) -> dict[str, object]:
        self.assert_session_id(session_id)
        return self.state

    def save(self, state: dict[str, object]) -> None:
        self.saved_state = state

    @staticmethod
    def assert_session_id(session_id: str) -> None:
        if session_id != "problem_42":
            raise AssertionError("The state must be saved for the active session.")


class MainRuntimeStateTests(unittest.TestCase):
    def test_status_output_contains_session_id_and_teaching_state(self) -> None:
        output = io.StringIO()

        with redirect_stdout(output):
            print_current_runtime_state(
                StubSessionManager(),
                StubTeachingStateRepository(),
            )

        displayed_text = output.getvalue()
        self.assertIn("session_id: problem_42", displayed_text)
        self.assertIn("current_teaching_state:", displayed_text)
        self.assertIn('"schema_version": 1', displayed_text)

    @patch("main.Runner.run", new_callable=AsyncMock)
    def test_teacher_response_triggers_state_update(self, mock_run: AsyncMock) -> None:
        mock_run.return_value = SimpleNamespace(
            final_output=TeachingStateUpdate(
                stage="solve",
                confirmed_steps_to_add=["formed_a_solution_plan"],
            )
        )
        repository = StatefulTeachingStateRepository()

        async def run_update() -> None:
            await update_teaching_state(
                "求函数的定义域",
                "请先写出分母不为零这一条件。",
                StubSessionManager(),
                repository,
            )

        import asyncio

        asyncio.run(run_update())

        mock_run.assert_awaited_once()
        self.assertIsNotNone(repository.saved_state)
        self.assertEqual(
            repository.saved_state["teaching_progress"]["stage"],
            "solve",
        )
        self.assertEqual(
            repository.saved_state["original_problem"]["problem_statement"],
            "求函数的定义域",
        )


if __name__ == "__main__":
    unittest.main()
