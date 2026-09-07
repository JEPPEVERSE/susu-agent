import sys
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.repositories.student_model_repository import StudentModelRepository
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.teaching_state import validate_teaching_state
from susu_agent.schemas.v02 import (
    ConceptMasteryPatch,
    ExecutionStateDelta,
    LearningEvidence,
    StudentModelPatch,
    TeachingExecution,
    TeachingStrategy,
    TeachingStrategyNode,
    TeachingTransition,
    VerificationIssue,
    VerificationReport,
)


class V02ArchitectureTests(unittest.TestCase):
    def test_passed_verification_cannot_contain_an_error(self) -> None:
        with self.assertRaises(ValidationError):
            VerificationReport(
                verdict="passed",
                summary="invalid",
                confidence="high",
                issues=[
                    VerificationIssue(
                        issue_id="issue_0",
                        issue_type="calculation_error",
                        severity="error",
                        evidence="2 + 2 was evaluated as 5.",
                        revision_instruction="Recalculate the step.",
                    )
                ],
            )

    def test_strategy_rejects_unknown_transition_node(self) -> None:
        with self.assertRaises(ValidationError):
            TeachingStrategy(
                strategy_id="strategy_0",
                summary="test",
                initial_node_id="teach_0",
                nodes=[
                    TeachingStrategyNode(
                        node_id="teach_0",
                        goal="test",
                        teaching_action="ask_question",
                        prompt_intent="ask",
                        disclosure_boundary="do not reveal the result",
                        transitions=[
                            TeachingTransition(
                                condition="correct",
                                next_node_id="teach_99",
                                action="advance",
                            )
                        ],
                    )
                ],
            )

    def test_execution_evidence_is_merged_deterministically(self) -> None:
        from susu_agent.agents.teaching_state_updater import apply_teaching_execution

        state = TeachingStateRepository.create_initial_state("problem_0")
        state["teaching_strategy"] = TeachingStrategy(
            strategy_id="strategy_0",
            summary="test",
            initial_node_id="teach_0",
            nodes=[
                TeachingStrategyNode(
                    node_id="teach_0",
                    goal="test",
                    teaching_action="ask_question",
                    prompt_intent="ask",
                    disclosure_boundary="do not reveal the result",
                )
            ],
        ).model_dump(mode="json")
        execution = TeachingExecution(
            response="请继续尝试。",
            assessment="partially_correct",
            state_delta=ExecutionStateDelta(
                current_strategy_node_id="teach_0",
                open_question="请继续尝试。",
            ),
            learning_evidence=[
                LearningEvidence(
                    evidence_id="problem_0_turn_0",
                    concept_id="equation_setup",
                    observation="列式正确，但计算尚未完成。",
                    assessment="mixed",
                    confidence="medium",
                )
            ],
        )

        updated = apply_teaching_execution(state, execution)
        self.assertEqual(updated["learning_evidence"][0]["concept_id"], "equation_setup")

    def test_continuing_execution_requires_a_visible_open_question(self) -> None:
        with self.assertRaises(ValidationError):
            TeachingExecution(
                response="请继续。",
                assessment="not_applicable",
                state_delta=ExecutionStateDelta(),
            )

    def test_registered_question_must_appear_in_response(self) -> None:
        with self.assertRaises(ValidationError):
            TeachingExecution(
                response="请思考下一步。",
                assessment="not_applicable",
                state_delta=ExecutionStateDelta(open_question="题目要求什么？"),
            )

    def test_state_rejects_an_orphan_progress_question(self) -> None:
        state = TeachingStateRepository.create_initial_state("problem_0")
        state["teaching_progress"]["open_question"] = "没有历史记录的问题"

        with self.assertRaisesRegex(ValueError, "requires an open history item"):
            validate_teaching_state(state)

    def test_student_model_patch_uses_optimistic_version_and_evidence_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = StudentModelRepository(Path(temp_directory) / "state.db")
            student = repository.get_or_create("student_0")
            updated = repository.apply_patch(
                student,
                StudentModelPatch(
                    base_model_version=1,
                    concept_updates=[
                        ConceptMasteryPatch(
                            concept_id="equation_setup",
                            subject="math",
                            proposed_mastery="learning",
                            evidence_summary="Two attempts showed partial understanding.",
                            evidence_ids=["evidence_1", "evidence_2"],
                            confidence="medium",
                        )
                    ],
                ),
            )

        self.assertEqual(updated["model_version"], 2)
        self.assertEqual(
            updated["learning_history"]["concept_mastery"][0]["concept_id"],
            "equation_setup",
        )


if __name__ == "__main__":
    unittest.main()
