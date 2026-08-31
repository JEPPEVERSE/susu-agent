import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from main import (
    build_math_tutor_input,
    persist_conversation_turn,
    print_current_runtime_state,
    update_teaching_state,
)
from susu_agent.agents.teaching_state_updater import TeachingStateUpdate
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository


class StubSessionManager:
    current_session_id = "problem_42"


class ArchiveSession:
    def __init__(self) -> None:
        self.items = [
            {"role": "user", "content": "previous question"},
            {"role": "assistant", "content": "previous teacher reply"},
            {"role": "tool", "content": "tool message"},
        ]
        self.persisted_items: list[dict[str, str]] = []

    async def get_items(self, limit: int) -> list[dict[str, str]]:
        return self.items[-limit:]

    async def add_items(self, items: list[dict[str, str]]) -> None:
        self.persisted_items.extend(items)


class ContextSessionManager:
    current_session_id = "problem_42"

    def __init__(self) -> None:
        self.current_session = ArchiveSession()


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

    def test_context_builder_controls_the_math_tutor_input(self) -> None:
        session_manager = ContextSessionManager()
        repository = StatefulTeachingStateRepository()

        import asyncio

        context_input = asyncio.run(
            build_math_tutor_input("current question", session_manager, repository)
        )

        self.assertIn("<teaching_context>", context_input)
        self.assertIn('"current_user_message": "current question"', context_input)
        self.assertIn("previous question", context_input)
        self.assertNotIn("tool message", context_input)

    def test_raw_conversation_is_persisted_after_the_model_reply(self) -> None:
        session_manager = ContextSessionManager()

        import asyncio

        asyncio.run(
            persist_conversation_turn(
                "current question",
                "teacher reply",
                session_manager,
            )
        )

        self.assertEqual(
            session_manager.current_session.persisted_items,
            [
                {"role": "user", "content": "current question"},
                {"role": "assistant", "content": "teacher reply"},
            ],
        )


if __name__ == "__main__":
    unittest.main()
