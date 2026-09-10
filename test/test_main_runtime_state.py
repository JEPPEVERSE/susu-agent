import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from main import (
    build_tutor_input,
    persist_conversation_turn,
    print_current_runtime_state,
)
from susu_agent.lesson_plan_loader import load_lesson_plan
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.solution import Solution, SolutionStep, SolveOutcome, TutorQuestion


def make_solution(problem_statement: str = "current question") -> Solution:
    return Solution(
        goal="完成题目",
        known_conditions=["已知条件"],
        strategy_summary="先明确目标，再完成推导。",
        steps=[
            SolutionStep(
                solution_step_id="step_0",
                lesson_plan_step_id="S1",
                title="明确目标",
                goal="确认题目要求",
                derivation="识别题目要求的数学对象。",
                result="目标已经明确。",
                tutor_questions=[
                    TutorQuestion(
                        question_id="question_0",
                        question="题目要求我们得到什么？",
                        teaching_goal="让学生明确交付目标",
                        expected_answer="说明题目目标",
                        answer_checkpoints=["正确说出目标"],
                        hint_ladder=["先看题目最后一句"],
                    )
                ],
            )
        ],
        final_answer="测试答案",
        verification=["回到原题核对目标"],
    )


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
        self.lesson_plan = load_lesson_plan("math")
        self.state = TeachingStateRepository.create_initial_state("problem_42")
        self.saved_state: dict[str, object] | None = None

    def get_or_create(self, session_id: str) -> dict[str, object]:
        self.assert_session_id(session_id)
        return self.state

    def get_or_create_with_lesson_plan(
        self,
        session_id: str,
    ) -> tuple[dict[str, object], object]:
        self.assert_session_id(session_id)
        return self.state, self.lesson_plan

    def save(self, state: dict[str, object], lesson_plan=None) -> None:
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

    def legacy_teacher_response_triggers_state_update(self) -> None:
        """v0.1 状态更新入口的历史场景，不进入当前测试集。"""
        mock_run = AsyncMock()
        mock_run.return_value = SimpleNamespace(
            final_output=TeachingStateUpdate(
                stage="execute",
                confirmed_steps_to_add=["formed_a_solution_plan"],
            )
        )
        repository = StatefulTeachingStateRepository()

        async def run_update() -> None:
            await update_teaching_state(
                "求函数的定义域",
                "请先写出分母不为零这一条件。",
                repository.state,
                repository.lesson_plan,
                repository,
            )

        import asyncio

        asyncio.run(run_update())

        mock_run.assert_awaited_once()
        updater_payload = json.loads(mock_run.await_args.kwargs["input"])
        self.assertIn("solution", updater_payload)
        self.assertIn("lesson_plan_instruction", updater_payload)
        self.assertEqual(
            updater_payload["lesson_plan_steps"][0],
            {"id": "S1", "name": "明确研究对象与交付目标"},
        )
        self.assertIn(
            "S1 明确研究对象与交付目标",
            updater_payload["lesson_plan_instruction"],
        )
        self.assertIsNotNone(repository.saved_state)
        self.assertEqual(
            repository.saved_state["teaching_progress"]["stage"],
            "execute",
        )
        self.assertEqual(
            repository.saved_state["original_problem"]["problem_statement"],
            "求函数的定义域",
        )

    @patch("main.Runner.run", new_callable=AsyncMock)
    def test_context_builder_controls_the_tutor_input(
        self,
        mock_run: AsyncMock,
    ) -> None:
        session_manager = ContextSessionManager()
        repository = StatefulTeachingStateRepository()
        mock_run.return_value = SimpleNamespace(
            final_output=SolveOutcome(status="solved", solution=make_solution())
        )

        import asyncio

        tutor_turn = asyncio.run(
            build_tutor_input("current question", session_manager, repository)
        )
        context_input = tutor_turn.context_input

        self.assertIn("<teaching_context>", context_input)
        self.assertIn('<lesson_plan_context subject="math"', context_input)
        self.assertIn('step_id="S1"', context_input)
        self.assertIn(
            "一、总纲：稳定解题是对题目系统进行降维、控制与闭环",
            context_input,
        )
        self.assertNotIn("F8 即时检查与原题闭环", context_input)
        self.assertIn('"lesson_plan": {', context_input)
        self.assertIn('"solution": {', context_input)
        self.assertIn('"solution_step_id": "step_0"', context_input)
        self.assertIn('"content_digest":', context_input)
        self.assertIn('"current_user_message": "current question"', context_input)
        self.assertIn("previous question", context_input)
        self.assertNotIn("tool message", context_input)
        self.assertEqual(tutor_turn.solution.goal, "完成题目")
        self.assertNotIn(
            "current_solution_step_id", repository.state["teaching_progress"]
        )

        asyncio.run(
            build_tutor_input("student follow-up", session_manager, repository)
        )
        mock_run.assert_awaited_once()

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
