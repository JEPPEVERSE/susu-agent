import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.agents.teaching_state_updater import (
    TeachingStateUpdate,
    apply_teaching_state_update,
    validate_teaching_execution_against_state,
)
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.solution import Solution, SolutionStep, TutorQuestion
from susu_agent.schemas.v02 import (
    ExecutionStateDelta,
    TeachingExecution,
    TeachingStrategy,
    TeachingStrategyNode,
)


class TeachingStateUpdateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = TeachingStateRepository.create_initial_state("problem_0")

    def test_incremental_update_is_merged_into_the_full_state(self) -> None:
        updated_state = apply_teaching_state_update(
            self.state,
            TeachingStateUpdate(
                stage="recall_knowledge",
                current_lesson_plan_step_id="S2",
                completed_lesson_plan_step_ids_to_add=["S1"],
                lesson_plan_step_summary="正在确认定义域限制。",
                confirmed_steps_to_add=["identified_known_conditions"],
                misconceptions_to_add=["confuses_domain_and_range"],
                open_question="What condition must the denominator satisfy?",
                next_teacher_action="ask_question",
                rolling_summary="The student needs to recall denominator restrictions.",
            ),
        )

        self.assertEqual(updated_state["teaching_progress"]["stage"], "recall_knowledge")
        self.assertEqual(
            updated_state["teaching_progress"]["current_lesson_plan_step_id"],
            "S2",
        )
        self.assertEqual(
            updated_state["teaching_progress"]["completed_lesson_plan_step_ids"],
            ["S1"],
        )
        self.assertIn(
            "identified_known_conditions",
            updated_state["teaching_progress"]["confirmed_steps"],
        )
        self.assertIn(
            "confuses_domain_and_range",
            updated_state["student_model"]["status"]["main_misconceptions"],
        )
        self.assertEqual(updated_state["open_question_history"][0]["status"], "open")
        self.assertEqual(
            updated_state["open_question_history"][0]["lesson_plan_step_id"],
            "S2",
        )

    def test_confirmed_steps_allow_a_chinese_teaching_description(self) -> None:
        updated_state = apply_teaching_state_update(
            self.state,
            TeachingStateUpdate(
                confirmed_steps_to_add=["学生识别出已知条件是 x+y=2"],
            ),
        )

        self.assertEqual(
            updated_state["teaching_progress"]["confirmed_steps"],
            ["学生识别出已知条件是 x+y=2"],
        )

    def test_student_answer_is_recorded_against_the_open_question(self) -> None:
        state_with_question = apply_teaching_state_update(
            self.state,
            TeachingStateUpdate(open_question="What condition must the denominator satisfy?"),
        )

        updated_state = apply_teaching_state_update(
            state_with_question,
            TeachingStateUpdate(
                answered_open_question_summary="The student said the denominator cannot be zero.",
                answered_open_question_understanding="correct",
                answered_open_question_assessment="The answer states the required restriction.",
            ),
        )

        question = updated_state["open_question_history"][0]
        self.assertEqual(question["status"], "answered")
        self.assertEqual(
            question["student_answer_summary"],
            "The student said the denominator cannot be zero.",
        )
        self.assertEqual(question["agent_assessment"]["understanding"], "correct")
        self.assertIsNotNone(question["resolved_at"])
        self.assertIsNone(updated_state["teaching_progress"]["open_question"])

    def test_partial_answer_fields_are_rejected(self) -> None:
        state_with_question = apply_teaching_state_update(
            self.state,
            TeachingStateUpdate(open_question="What condition must the denominator satisfy?"),
        )

        with self.assertRaises(ValueError):
            apply_teaching_state_update(
                state_with_question,
                TeachingStateUpdate(
                    answered_open_question_summary="The student is unsure.",
                ),
            )

    def test_unknown_lesson_plan_step_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            apply_teaching_state_update(
                self.state,
                TeachingStateUpdate(
                    current_lesson_plan_step_id="S99",
                ),
            )

    def test_solution_step_progress_and_question_are_linked(self) -> None:
        solution = Solution(
            goal="完成测试题",
            strategy_summary="执行两个题目步骤。",
            steps=[
                SolutionStep(
                    solution_step_id="step_0",
                    lesson_plan_step_id="S1",
                    title="明确目标",
                    goal="明确目标",
                    derivation="目标已经明确。",
                    result="完成目标识别。",
                ),
                SolutionStep(
                    solution_step_id="step_1",
                    lesson_plan_step_id="S3",
                    title="分析动静",
                    goal="分析变量关系",
                    derivation="分析变量之间的约束。",
                    result="得到控制参数。",
                    tutor_questions=[
                        TutorQuestion(
                            question_id="question_1",
                            question="哪些变量可以独立变化？",
                            teaching_goal="识别控制参数",
                            expected_answer="说明变量之间的依赖关系。",
                        )
                    ],
                ),
            ],
            final_answer="测试结论",
        )
        self.state["original_problem"] = {
            "problem_statement": "测试题",
            "status": "solved",
            "clarification_questions": [],
            "clarification_context": [],
        }
        self.state["solution"] = solution.model_dump(mode="json")

        updated_state = apply_teaching_state_update(
            self.state,
            TeachingStateUpdate(
                current_solution_step_id="step_1",
                current_solution_question_id="question_1",
                completed_solution_step_ids_to_add=["step_0"],
                solution_step_summary="正在分析变量关系。",
                open_question="哪些变量可以独立变化？",
            ),
        )

        progress = updated_state["teaching_progress"]
        self.assertEqual(progress["current_solution_step_id"], "step_1")
        self.assertEqual(progress["current_lesson_plan_step_id"], "S3")
        self.assertEqual(progress["completed_solution_step_ids"], ["step_0"])
        self.assertEqual(
            progress["current_solution_question_id"],
            "question_1",
        )
        self.assertEqual(
            updated_state["open_question_history"][0]["solution_step_id"],
            "step_1",
        )
        self.assertEqual(
            updated_state["open_question_history"][0]["solution_question_id"],
            "question_1",
        )

    def test_unknown_solution_step_id_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            apply_teaching_state_update(
                self.state,
                TeachingStateUpdate(current_solution_step_id="step_99"),
            )

    def test_answer_cannot_be_attached_without_an_open_question(self) -> None:
        execution = TeachingExecution(
            response="题目要求什么？",
            assessment="correct",
            state_delta=ExecutionStateDelta(
                answered_open_question_summary="学生给出了回答。",
                answered_open_question_understanding="correct",
                answered_open_question_assessment="回答正确。",
                open_question="题目要求什么？",
            ),
        )

        with self.assertRaisesRegex(ValueError, "no open question"):
            validate_teaching_execution_against_state(self.state, execution)

    def test_expression_agent_can_phrase_a_node_aligned_question(self) -> None:
        self.state["teaching_strategy"] = TeachingStrategy(
            strategy_id="strategy_0",
            summary="test",
            initial_node_id="teach_0",
            nodes=[
                TeachingStrategyNode(
                    node_id="teach_0",
                    goal="明确目标",
                    teaching_action="ask_question",
                    prompt_intent="询问题目目标",
                    hint_ladder=["最后要求计算哪个量？"],
                    disclosure_boundary="不透露答案",
                )
            ],
        ).model_dump(mode="json")
        self.state["teaching_progress"]["current_strategy_node_id"] = "teach_0"
        execution = TeachingExecution(
            response="余弦函数是递增还是递减？",
            assessment="not_applicable",
            state_delta=ExecutionStateDelta(open_question="余弦函数是递增还是递减？"),
        )

        validate_teaching_execution_against_state(self.state, execution)


if __name__ == "__main__":
    unittest.main()
