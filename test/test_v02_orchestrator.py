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
from susu_agent.schemas.solution import Solution, SolutionStep, SolveOutcome, TutorQuestion
from susu_agent.schemas.v02 import (
    ExecutionStateDelta,
    TeachingExecution,
    TeachingStrategy,
    TeachingStrategyNode,
    TeachingTransition,
    VerificationIssue,
    VerificationReport,
)


def result(value: object) -> SimpleNamespace:
    return SimpleNamespace(final_output=value)


class V02OrchestratorTests(unittest.TestCase):
    @patch("susu_agent.orchestrator.Runner.run", new_callable=AsyncMock)
    def test_interrupted_revision_resumes_from_persisted_feedback(
        self, mock_run: AsyncMock
    ) -> None:
        solution = Solution(
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
                )
            ],
            final_answer="测试答案",
        )
        needs_revision = VerificationReport(
            verdict="needs_revision",
            summary="第一步需要补充依据。",
            checked_solution_step_ids=["step_0"],
            issues=[
                VerificationIssue(
                    issue_id="issue_0",
                    affected_solution_step_ids=["step_0"],
                    issue_type="derivation_gap",
                    severity="error",
                    evidence="缺少必要推导。",
                    revision_instruction="补充必要推导。",
                )
            ],
            confidence="high",
        )
        passed = VerificationReport(
            verdict="passed",
            summary="修订后的解题图通过验证。",
            checked_solution_step_ids=["step_0"],
            confidence="high",
        )

        with tempfile.TemporaryDirectory() as temp_directory:
            database = Path(temp_directory) / "runtime.db"
            states = TeachingStateRepository(database)
            orchestrator = V02Orchestrator(
                states,
                StudentModelRepository(database),
                memory_enabled=False,
            )
            state, lesson_plan = states.get_or_create_with_lesson_plan("problem_0")
            state["original_problem"] = {
                "problem_statement": "测试题",
                "status": "pending",
                "clarification_questions": [],
                "clarification_context": [],
            }
            mock_run.side_effect = [
                result(SolveOutcome(status="solved", solution=solution)),
                result(needs_revision),
                RuntimeError("temporary provider failure"),
            ]

            with self.assertRaisesRegex(RuntimeError, "temporary provider failure"):
                asyncio.run(
                    orchestrator._solve_and_verify(state, lesson_plan, "测试题")
                )

            persisted_state, lesson_plan = states.get_or_create_with_lesson_plan(
                "problem_0"
            )
            mock_run.reset_mock()
            mock_run.side_effect = [
                result(SolveOutcome(status="solved", solution=solution)),
                result(passed),
            ]
            resumed_state, response = asyncio.run(
                orchestrator._solve_and_verify(
                    persisted_state, lesson_plan, "测试题"
                )
            )

        self.assertIsNone(response)
        self.assertEqual(resumed_state["verification_report"]["verdict"], "passed")
        self.assertEqual(resumed_state["v03_meta"]["solution_revision"], 1)
        self.assertEqual(mock_run.await_count, 2)
        resumed_solver_input = mock_run.await_args_list[0].kwargs["input"]
        self.assertIn('"previous_solution": {', resumed_solver_input)
        self.assertIn('"revision_context": {', resumed_solver_input)

    def test_unplanned_state_is_not_mistaken_for_completed_teaching(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            database = Path(temp_directory) / "runtime.db"
            states = TeachingStateRepository(database)
            states.get_or_create("problem_0")
            orchestrator = V02Orchestrator(
                states,
                StudentModelRepository(database),
                memory_enabled=False,
            )

            summarized = asyncio.run(
                orchestrator.summarize_if_needed("problem_0")
            )

        self.assertFalse(summarized)

    @patch("susu_agent.orchestrator.Runner.run", new_callable=AsyncMock)
    def test_unresolved_problem_does_not_reach_verifier(
        self, mock_run: AsyncMock
    ) -> None:
        mock_run.return_value = result(
            SolveOutcome(
                status="incomplete",
                clarification_questions=["请补充函数的定义域。"],
                reason="缺少定义域。",
            )
        )

        with tempfile.TemporaryDirectory() as temp_directory:
            database = Path(temp_directory) / "runtime.db"
            orchestrator = V02Orchestrator(
                TeachingStateRepository(database),
                StudentModelRepository(database),
                memory_enabled=False,
            )
            response, state = asyncio.run(
                orchestrator.run_turn("problem_0", "求函数最大值", [])
            )

        self.assertIn("请补充函数的定义域", response)
        self.assertEqual(state["original_problem"]["status"], "incomplete")
        self.assertIsNone(state["verification_report"])
        self.assertEqual(mock_run.await_count, 1)
        self.assertEqual(mock_run.await_args.args[0].name, "solution_agent")

    def test_subject_route_requires_a_registered_lesson_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            database = Path(temp_directory) / "runtime.db"
            with self.assertRaisesRegex(ValueError, "no registered lesson plan"):
                V02Orchestrator(
                    TeachingStateRepository(database, default_subject="physics"),
                    StudentModelRepository(database),
                    memory_enabled=False,
                )

    @patch("susu_agent.orchestrator.Runner.run", new_callable=AsyncMock)
    def test_problem_artifacts_are_cached_after_the_first_turn(
        self, mock_run: AsyncMock
    ) -> None:
        solution = Solution(
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
                    answer_checkpoints=["说出题目目标"],
                    disclosure_boundary="不透露最终答案",
                    transitions=[
                        TeachingTransition(condition="correct", action="advance"),
                        TeachingTransition(condition="partially_correct", next_node_id="teach_0", action="give_hint"),
                        TeachingTransition(condition="incorrect", next_node_id="teach_0", action="retry"),
                        TeachingTransition(condition="no_idea", next_node_id="teach_0", action="give_hint"),
                        TeachingTransition(condition="unclear", next_node_id="teach_0", action="retry"),
                        TeachingTransition(condition="student_requests_solution", action="complete"),
                    ],
                )
            ],
        )
        first_execution = TeachingExecution(
            feedback="",
            assessment="not_applicable",
            state_delta=ExecutionStateDelta(
                open_question="题目要求什么？",
                open_question_target_checkpoint_indices=[0],
            ),
        )
        second_execution = TeachingExecution(
            feedback="对，目标已经找到了。",
            assessment="correct",
            state_delta=ExecutionStateDelta(
                answered_open_question_summary="学生说出了目标。",
                answered_open_question_feedback="回答覆盖目标检查点。",
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
        invalid_solver_outcome = json.dumps(
            {"schema_version": 1, "status": "solved", "solution": None},
            ensure_ascii=False,
        )
        mock_run.side_effect = [
            result(invalid_solver_outcome),
            result(SolveOutcome(status="solved", solution=solution)),
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
                memory_enabled=False,
            )

            async def run() -> tuple[str, str]:
                first, _ = await orchestrator.run_turn("problem_0", "测试题", [])
                second, _ = await orchestrator.run_turn(
                    "problem_0", "要求得到测试答案", []
                )
                return first, second

            first_response, second_response = asyncio.run(run())

        self.assertEqual(first_response, "题目要求什么？")
        self.assertEqual(second_response, second_execution.feedback)
        self.assertEqual(mock_run.await_count, 7)
        self.assertEqual(
            [call.args[0].name for call in mock_run.await_args_list],
            [
                "solution_agent",
                "solution_agent",
                "solution_verifier",
                "teaching_planner",
                "teaching_executor",
                "teaching_executor",
                "teaching_executor",
            ],
        )
        schema_repair_prompt = mock_run.await_args_list[1].kwargs["input"]
        self.assertIn("上一次输出未通过结构化 Schema 校验", schema_repair_prompt)
        execution_repair_prompt = mock_run.await_args_list[5].kwargs["input"]
        self.assertIn("上一次输出未通过运行时契约校验", execution_repair_prompt)


if __name__ == "__main__":
    unittest.main()
