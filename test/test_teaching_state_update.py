import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.solution import Solution, SolutionStep, TutorQuestion
from susu_agent.schemas.v02 import (
    ExecutionStateDelta,
    TeachingExecution,
    TeachingStrategy,
    TeachingStrategyNode,
    TeachingTransition,
)
from susu_agent.teaching_runtime import (
    MAX_NODE_ATTEMPTS,
    apply_teaching_execution,
    render_teaching_response,
    resolve_execution_decision,
    validate_teaching_execution_against_state as validate_v02_execution,
)


def _transitions(node_id: str, next_node_id: str | None):
    return [
        TeachingTransition(condition="correct", next_node_id=next_node_id, action="advance"),
        TeachingTransition(condition="partially_correct", next_node_id=node_id, action="give_hint"),
        TeachingTransition(condition="incorrect", next_node_id=node_id, action="retry"),
        TeachingTransition(condition="no_idea", next_node_id=node_id, action="give_hint"),
        TeachingTransition(condition="unclear", next_node_id=node_id, action="retry"),
        TeachingTransition(condition="student_requests_solution", action="complete"),
    ]


def make_runtime_state() -> dict[str, object]:
    state = TeachingStateRepository.create_initial_state("problem_0")
    solution = Solution(
        goal="完成测试题",
        strategy_summary="先识别两个条件，再继续。",
        steps=[
            SolutionStep(
                solution_step_id="step_0", lesson_plan_step_id="S1",
                title="明确目标", goal="识别条件", derivation="识别目标与范围。",
                result="条件明确。", concept_ids=["problem_identification"],
                tutor_questions=[TutorQuestion(
                    question_id="question_0", question="目标和范围是什么？",
                    teaching_goal="识别条件", expected_answer="目标与范围",
                )],
            ),
            SolutionStep(
                solution_step_id="step_1", lesson_plan_step_id="S3",
                title="继续推导", goal="建立关系", derivation="建立关系。",
                result="关系成立。", concept_ids=["equation_setup"],
                tutor_questions=[TutorQuestion(
                    question_id="question_1", question="下一步关系是什么？",
                    teaching_goal="建立关系", expected_answer="关系式",
                )],
            ),
        ],
        final_answer="测试答案",
    )
    strategy = TeachingStrategy(
        strategy_id="strategy_0", summary="测试策略", initial_node_id="teach_0",
        nodes=[
            TeachingStrategyNode(
                node_id="teach_0", solution_step_id="step_0",
                solution_question_id="question_0", goal="识别条件",
                teaching_action="ask_question", prompt_intent="询问目标与范围",
                answer_checkpoints=["目标", "范围"],
                hint_ladder=["先看最后一句", "再看定义域"],
                disclosure_boundary="不透露答案",
                transitions=_transitions("teach_0", "teach_1"),
            ),
            TeachingStrategyNode(
                node_id="teach_1", solution_step_id="step_1",
                solution_question_id="question_1", goal="建立关系",
                teaching_action="ask_question", prompt_intent="询问关系",
                answer_checkpoints=["关系式"], disclosure_boundary="不透露答案",
                transitions=_transitions("teach_1", None),
            ),
        ],
    )
    state["original_problem"] = {
        "problem_statement": "测试题", "status": "solved",
        "clarification_questions": [], "clarification_context": [],
    }
    state["solution"] = solution.model_dump(mode="json")
    state["teaching_strategy"] = strategy.model_dump(mode="json")
    state["teaching_progress"]["current_strategy_node_id"] = "teach_0"
    return state


class V02TeachingRuntimeTests(unittest.TestCase):
    def test_checkpoints_accumulate_across_answers_and_advance(self) -> None:
        state = apply_teaching_execution(
            make_runtime_state(),
            TeachingExecution(
                assessment="not_applicable",
                state_delta=ExecutionStateDelta(
                    open_question="目标是什么？",
                    open_question_target_checkpoint_indices=[0],
                ),
            ),
        )
        state = apply_teaching_execution(
            state,
            TeachingExecution(
                feedback="目标正确。", assessment="partially_correct",
                state_delta=ExecutionStateDelta(
                    answered_open_question_summary="学生答对目标。",
                    answered_open_question_feedback="范围尚未回答。",
                    satisfied_checkpoint_indices_to_add=[0],
                    open_question="再说范围是什么？",
                    open_question_target_checkpoint_indices=[1],
                ),
            ),
        )
        execution = TeachingExecution(
            feedback="范围正确。", assessment="correct",
            state_delta=ExecutionStateDelta(
                answered_open_question_summary="学生答对范围。",
                answered_open_question_feedback="当前节点检查点均满足。",
                open_question="下一步关系是什么？",
                open_question_target_checkpoint_indices=[0],
            ),
        )
        self.assertEqual(resolve_execution_decision(state, execution).target_node_id, "teach_1")
        state = apply_teaching_execution(state, execution)
        self.assertEqual(state["teaching_progress"]["current_strategy_node_id"], "teach_1")
        self.assertEqual(
            state["teaching_progress"]["satisfied_checkpoint_ids"],
            ["teach_0:checkpoint_0", "teach_0:checkpoint_1"],
        )

    def test_retry_limit_forces_advance(self) -> None:
        state = make_runtime_state()
        state["teaching_progress"]["attempts_by_node"]["teach_0"] = MAX_NODE_ATTEMPTS - 1
        state["open_question_history"] = [{
            "question_id": "question_0", "question": "范围是什么？",
            "strategy_node_id": "teach_0", "solution_question_id": "question_0",
            "target_checkpoint_indices": [1], "status": "open",
            "asked_at": state["updated_at"], "student_answer_summary": None,
            "assessment": "not_answered", "assessment_reason": "", "resolved_at": None,
        }]
        execution = TeachingExecution(
            feedback="我补充范围。", assessment="incorrect",
            state_delta=ExecutionStateDelta(
                answered_open_question_summary="仍未答出范围。",
                answered_open_question_feedback="达到重试上限。",
                open_question="下一步关系是什么？",
                open_question_target_checkpoint_indices=[0],
            ),
        )
        decision = validate_v02_execution(state, execution)
        self.assertTrue(decision.forced_advance)
        self.assertTrue(decision.reveal_current_answer)
        self.assertEqual(decision.target_node_id, "teach_1")

    def test_second_answer_reveals_answer_explanation_and_next_question(self) -> None:
        for second_assessment in ("incorrect", "correct"):
            with self.subTest(second_assessment=second_assessment):
                state = apply_teaching_execution(
                    make_runtime_state(),
                    TeachingExecution(
                        assessment="not_applicable",
                        state_delta=ExecutionStateDelta(
                            open_question="目标是什么？",
                            open_question_target_checkpoint_indices=[0],
                        ),
                    ),
                )
                state = apply_teaching_execution(
                    state,
                    TeachingExecution(
                        feedback="再想想范围。",
                        assessment="partially_correct",
                        state_delta=ExecutionStateDelta(
                            answered_open_question_summary="学生只答出了目标。",
                            answered_open_question_feedback="尚未说明范围。",
                            satisfied_checkpoint_indices_to_add=[0],
                            open_question="范围是什么？",
                            open_question_target_checkpoint_indices=[1],
                        ),
                    ),
                )
                second_execution = TeachingExecution(
                    feedback="这是你的第二轮回答。",
                    assessment=second_assessment,
                    state_delta=ExecutionStateDelta(
                        answered_open_question_summary="学生第二轮回答范围。",
                        answered_open_question_feedback="第二轮回答已完成判定。",
                        open_question="下一步关系是什么？",
                        open_question_target_checkpoint_indices=[0],
                    ),
                )

                decision = resolve_execution_decision(state, second_execution)
                response = render_teaching_response(second_execution, state)

                self.assertTrue(decision.reveal_current_answer)
                self.assertEqual(decision.target_node_id, "teach_1")
                self.assertIn("当前问题的正确答案：范围", response)
                self.assertIn("这一步的目的：识别条件", response)
                self.assertIn("背后原理：识别目标与范围。", response)
                self.assertTrue(response.endswith("下一步关系是什么？"))
                updated_state = apply_teaching_execution(state, second_execution)
                self.assertEqual(
                    updated_state["teaching_progress"]["current_strategy_node_id"],
                    "teach_1",
                )
                self.assertEqual(
                    updated_state["open_question_history"][-1]["question"],
                    "下一步关系是什么？",
                )
                self.assertEqual(
                    updated_state["open_question_history"][-1]["status"],
                    "open",
                )

    def test_invalid_checkpoint_target_is_rejected(self) -> None:
        execution = TeachingExecution(
            feedback="", assessment="not_applicable",
            state_delta=ExecutionStateDelta(
                open_question="继续。", open_question_target_checkpoint_indices=[99]
            ),
        )
        with self.assertRaisesRegex(ValueError, "checkpoint targets"):
            validate_v02_execution(make_runtime_state(), execution)

    def test_initial_question_must_target_one_atomic_checkpoint(self) -> None:
        execution = TeachingExecution(
            feedback="",
            assessment="not_applicable",
            state_delta=ExecutionStateDelta(
                open_question="请依次识别目标和范围。",
                open_question_target_checkpoint_indices=[0, 1],
            ),
        )

        with self.assertRaisesRegex(ValueError, "one atomic checkpoint"):
            validate_v02_execution(make_runtime_state(), execution)


class LegacyTeachingStateUpdateExamples:
    """保留旧场景作迁移参考；不属于当前可执行测试集。"""
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
            feedback="",
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
            feedback="",
            assessment="not_applicable",
            state_delta=ExecutionStateDelta(open_question="余弦函数是递增还是递减？"),
        )

        validate_teaching_execution_against_state(self.state, execution)


if __name__ == "__main__":
    unittest.main()
