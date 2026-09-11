import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.lesson_plan_loader import load_lesson_plan
from susu_agent.memory.repositories import MemoryRepository
from susu_agent.orchestrator import V03Orchestrator
from susu_agent.repositories.student_model_repository import StudentModelRepository
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.problem_representation import ProblemRepresentation
from susu_agent.schemas.solution import Solution, SolutionStep, SolveOutcome
from susu_agent.schemas.v03 import (
    TeachingStrategy,
    TeachingStrategyNode,
    TeachingTransition,
    TeachingExecution,
    ExecutionStateDelta,
    VerificationIssue,
    VerificationReport,
)


def solution() -> Solution:
    return Solution(
        goal="求最小值",
        strategy_summary="利用约束化简。",
        steps=[
            SolutionStep(
                solution_step_id="step_0",
                lesson_plan_step_id="S3",
                title="降低自由度",
                goal="消去一个变量",
                derivation="由 x+y=2 得 y=2-x。",
                result="目标成为一元函数。",
                concept_ids=["freeze_variable"],
            )
        ],
        final_answer="最小值为 2。",
    )


def representation() -> ProblemRepresentation:
    return ProblemRepresentation(
        problem_id="problem_contract",
        subject="math",
        goal_type="extremum",
        problem_type="unknown",
        objects=["x", "y"],
        conditions=["x+y=2"],
        goal="求 x²+y² 的最小值",
        structural_features={"degrees_of_freedom": 2},
        concept_ids=["freeze_variable"],
    )


def strategy(question_card_id: str | None = None) -> TeachingStrategy:
    return TeachingStrategy(
        strategy_id="strategy_contract",
        summary="先降低自由度。",
        initial_node_id="teach_0",
        nodes=[
            TeachingStrategyNode(
                node_id="teach_0",
                solution_step_id="step_0",
                question_card_id=question_card_id,
                retrieval_evidence_ids=(
                    [question_card_id] if question_card_id is not None else []
                ),
                goal="识别变量约束",
                teaching_action="ask_question",
                prompt_intent="询问如何降低自由度",
                answer_checkpoints=["提出消元或冻结变量"],
                disclosure_boundary="不直接给出化简式",
                transitions=[
                    TeachingTransition(condition="correct", action="complete"),
                    TeachingTransition(
                        condition="partially_correct",
                        next_node_id="teach_0",
                        action="give_hint",
                    ),
                    TeachingTransition(
                        condition="incorrect",
                        next_node_id="teach_0",
                        action="retry",
                    ),
                    TeachingTransition(
                        condition="no_idea",
                        next_node_id="teach_0",
                        action="give_hint",
                    ),
                    TeachingTransition(
                        condition="unclear",
                        next_node_id="teach_0",
                        action="retry",
                    ),
                    TeachingTransition(
                        condition="student_requests_solution", action="complete"
                    ),
                ],
            )
        ],
    )


class V03ContractTests(unittest.TestCase):
    def test_free_text_problem_labels_are_normalized_for_retrieval(self) -> None:
        represented = ProblemRepresentation(
            problem_id="problem_trigonometric",
            subject="math",
            goal_type="求最大值",
            problem_type="三角条件约束下的最值问题",
            goal="求 cos α 的最大值",
        )

        self.assertEqual(represented.goal_type, "extremum")
        self.assertEqual(represented.problem_type, "trigonometry")

    def test_indirect_solution_route_cannot_pass_verification(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot pass verification"):
            VerificationReport(
                verdict="passed",
                summary="答案虽然正确，但路线明显绕远。",
                checked_solution_step_ids=["step_0"],
                confidence="high",
                route_quality="needs_simplification",
                simpler_route_summary="统一成正切后二次配方即可。",
                issues=[
                    VerificationIssue(
                        issue_id="issue_0",
                        affected_solution_step_ids=["step_0"],
                        issue_type="route_inefficiency",
                        severity="warning",
                        evidence="引入辅助变量和判别式造成不必要绕行。",
                        revision_instruction="改用正切代换和配方。",
                    )
                ],
            )

    def test_memory_mode_change_invalidates_cached_problem_artifacts(self) -> None:
        state = {
            "original_problem": {"problem_statement": "测试题", "status": "solved"},
            "solution": {"cached": True},
            "problem_representation": {"cached": True},
            "verification_report": {"verdict": "passed"},
            "teaching_strategy": {"cached": True},
            "retrieval_cache": {"planning": {"evidence": []}},
            "memory_update_proposal_ids": ["proposal_0"],
            "open_question_history": [
                {
                    "status": "open",
                    "resolved_at": None,
                    "solution_question_id": "question_0",
                }
            ],
            "v03_meta": {"memory_enabled": False, "summary_completed": True},
        }

        V03Orchestrator._invalidate_for_memory_mode_change(state)

        self.assertIsNone(state["solution"])
        self.assertIsNone(state["problem_representation"])
        self.assertIsNone(state["verification_report"])
        self.assertIsNone(state["teaching_strategy"])
        self.assertEqual(state["retrieval_cache"], {})
        self.assertEqual(state["original_problem"]["status"], "pending")
        self.assertEqual(state["open_question_history"][0]["status"], "abandoned")
        self.assertIsNone(
            state["open_question_history"][0]["solution_question_id"]
        )
        self.assertFalse(state["v03_meta"]["summary_completed"])

    @patch("susu_agent.orchestrator.Runner.run", new_callable=AsyncMock)
    def test_memory_enabled_first_turn_runs_the_full_v03_path(
        self, mock_run: AsyncMock
    ) -> None:
        solved = solution()
        represented = representation()
        report = VerificationReport(
            verdict="passed",
            summary="步骤和条件均已核验。",
            checked_solution_step_ids=["step_0"],
            checked_condition_indices=[0],
            evidence_sufficient=True,
            confidence="high",
        )
        planned = strategy("question_freeze_variable")
        executed = TeachingExecution(
            feedback="",
            assessment="not_applicable",
            state_delta=ExecutionStateDelta(
                open_question="面对两个受约束变量，可以怎样降低自由度？",
                open_question_target_checkpoint_indices=[0],
            ),
        )
        mock_run.side_effect = [
            SimpleNamespace(
                final_output=SolveOutcome(
                    status="solved",
                    solution=solved,
                    problem_representation=represented,
                )
            ),
            SimpleNamespace(final_output=report),
            SimpleNamespace(final_output=planned),
            SimpleNamespace(final_output=executed),
        ]

        with tempfile.TemporaryDirectory() as temp_directory:
            data_path = Path(temp_directory)
            runtime_db = data_path / "runtime.db"
            memory_repository = MemoryRepository(data_path / "memory.db")
            orchestrator = V03Orchestrator(
                TeachingStateRepository(runtime_db),
                StudentModelRepository(runtime_db),
                memory_enabled=True,
                memory_repository=memory_repository,
            )

            response, state = asyncio.run(
                orchestrator.run_turn(
                    "problem_v03",
                    "已知 x+y=2，求 x²+y² 的最小值。",
                    [],
                )
            )

        self.assertIn("面对两个受约束变量", response)
        self.assertTrue(state["v03_meta"]["memory_enabled"])
        self.assertEqual(
            set(state["retrieval_cache"]), {"solution", "planning", "execution"}
        )
        self.assertEqual(
            state["teaching_strategy"]["nodes"][0]["question_card_id"],
            "question_freeze_variable",
        )
        self.assertEqual(mock_run.await_count, 4)

    def test_passed_verification_must_cover_all_problem_conditions(self) -> None:
        report = VerificationReport(
            verdict="passed",
            summary="步骤正确。",
            checked_solution_step_ids=["step_0"],
            checked_condition_indices=[],
            evidence_sufficient=True,
            confidence="high",
        )

        with self.assertRaisesRegex(ValueError, "every represented condition"):
            V03Orchestrator._validate_verification_references(
                report, solution(), representation()
            )

    def test_strategy_may_only_adopt_returned_question_cards(self) -> None:
        teaching_state = {
            "retrieval_cache": {
                "planning": {
                    "evidence": [
                        {
                            "memory_id": "question_freeze_variable",
                            "memory_type": "question_card",
                        }
                    ]
                }
            }
        }
        V03Orchestrator._validate_strategy_references(
            strategy("question_freeze_variable"),
            solution(),
            teaching_state=teaching_state,
        )

        with self.assertRaisesRegex(ValueError, "unreturned memory"):
            V03Orchestrator._validate_strategy_references(
                strategy("question_not_retrieved"),
                solution(),
                teaching_state=teaching_state,
            )

    def test_solution_concepts_must_be_in_problem_representation(self) -> None:
        invalid_representation = representation().model_copy(
            update={"concept_ids": []}
        )
        orchestrator = object.__new__(V03Orchestrator)
        orchestrator.memory_enabled = True

        with self.assertRaisesRegex(ValueError, "omits Solution concepts"):
            orchestrator._validate_solve_outcome(
                SolveOutcome(
                    status="solved",
                    solution=solution(),
                    problem_representation=invalid_representation,
                ),
                load_lesson_plan("math"),
            )


if __name__ == "__main__":
    unittest.main()
