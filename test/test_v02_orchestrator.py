import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.orchestrator import V02Orchestrator
from susu_agent.repositories.student_model_repository import StudentModelRepository
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.solution import Solution, SolutionStep, TutorQuestion
from susu_agent.schemas.v02 import (
    ExecutionStateDelta,
    TeachingExecution,
    TeachingStrategy,
    TeachingStrategyNode,
    VerificationReport,
)


def result(value: object) -> SimpleNamespace:
    return SimpleNamespace(final_output=value)


class V02OrchestratorTests(unittest.TestCase):
    @patch("susu_agent.orchestrator.Runner.run", new_callable=AsyncMock)
    def test_problem_artifacts_are_cached_after_the_first_turn(
        self, mock_run: AsyncMock
    ) -> None:
        solution = Solution(
            problem_statement="测试题",
            problem_status="solvable",
            goal="完成测试题",
            strategy_summary="先明确目标。",
            steps=[
                SolutionStep(
                    solution_step_id="step_0",
                    lesson_plan_step_id="S1",
                    title="明确目标",
                    goal="明确目标",
                    derivation="识别题目要求。",
                    result="目标明确。",
                    tutor_questions=[
                        TutorQuestion(
                            question_id="question_0",
                            question="题目要求什么？",
                            teaching_goal="明确目标",
                            expected_answer="说出题目目标",
                        )
                    ],
                )
            ],
            final_answer="测试答案",
        )
        verification = VerificationReport(
            verdict="passed",
            summary="解题图通过验证。",
            checked_solution_step_ids=["step_0"],
            confidence="high",
        )
        strategy = TeachingStrategy(
            strategy_id="strategy_0",
            summary="引导学生先明确目标。",
            initial_node_id="teach_0",
            nodes=[
                TeachingStrategyNode(
                    node_id="teach_0",
                    solution_step_id="step_0",
                    solution_question_id="question_0",
                    goal="明确目标",
                    teaching_action="ask_question",
                    prompt_intent="询问题目目标",
                    disclosure_boundary="不透露最终答案",
                )
            ],
        )
        first_execution = TeachingExecution(
            response="先说说：题目要求什么？",
            assessment="not_applicable",
            state_delta=ExecutionStateDelta(open_question="题目要求什么？"),
        )
        second_execution = TeachingExecution(
            response="对，目标已经找到了。题目要求什么？",
            assessment="correct",
            state_delta=ExecutionStateDelta(
                answered_open_question_summary="学生说出了目标。",
                answered_open_question_understanding="correct",
                answered_open_question_assessment="回答覆盖目标检查点。",
                open_question="题目要求什么？",
            ),
        )
        invalid_first_execution = json.dumps(
            {
                "schema_version": 1,
                "response": "先想一想余弦函数是递增还是递减的？",
                "assessment": "not_applicable",
                "state_delta": {},
                "learning_evidence": [],
                "control_signal": "continue",
                "control_reason": "",
            },
            ensure_ascii=False,
        )
        mock_run.side_effect = [
            result(solution),
            result(verification),
            result(strategy),
            result(invalid_first_execution),
            result(first_execution),
            result(second_execution),
        ]

        with tempfile.TemporaryDirectory() as temp_directory:
            database = Path(temp_directory) / "runtime.db"
            orchestrator = V02Orchestrator(
                TeachingStateRepository(database),
                StudentModelRepository(database),
            )

            async def run() -> tuple[str, str]:
                first, _ = await orchestrator.run_turn("problem_0", "测试题", [])
                second, _ = await orchestrator.run_turn(
                    "problem_0", "要求得到测试答案", []
                )
                return first, second

            first_response, second_response = asyncio.run(run())

        self.assertEqual(first_response, first_execution.response)
        self.assertEqual(second_response, second_execution.response)
        self.assertEqual(mock_run.await_count, 6)
        self.assertEqual(
            [call.args[0].name for call in mock_run.await_args_list],
            [
                "solution_agent",
                "solution_verifier",
                "teaching_planner",
                "teaching_executor",
                "teaching_executor",
                "teaching_executor",
            ],
        )
        repair_prompt = mock_run.await_args_list[4].kwargs["input"]
        self.assertIn("上一次输出未通过运行时契约校验", repair_prompt)


if __name__ == "__main__":
    unittest.main()
