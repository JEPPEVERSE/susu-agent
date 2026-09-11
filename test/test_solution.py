import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.agents.math_solver import (
    MATH_SOLUTION_USES_NATIVE_OUTPUT,
    MathSolverRunContext,
    build_math_solver_input,
    math_solution_agent,
    provide_math_solver_instructions,
    validate_solution_lesson_plan_references,
)
from susu_agent.agents.solution_verifier import build_solution_verifier_input
from susu_agent.lesson_plan_loader import load_lesson_plan
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.solution import (
    Solution,
    SolutionStep,
    SolveOutcome,
    TutorQuestion,
)


def make_solution() -> Solution:
    return Solution(
        goal="求 x²+y² 的最小值",
        known_conditions=["x+y=2", "x、y 为实数"],
        strategy_summary="识别一个自由参数，再建立目标的下界。",
        steps=[
            SolutionStep(
                solution_step_id="step_0",
                lesson_plan_step_id="S3",
                title="分析变量约束",
                goal="判断 x 与 y 是否独立变化",
                derivation="由 x+y=2 可知选定 x 后 y=2-x。",
                result="问题只有一个连续自由参数。",
                concept_ids=["variable_constraint"],
                tutor_questions=[
                    TutorQuestion(
                        question_id="question_0",
                        question="固定 x 后，y 还能任意选择吗？",
                        teaching_goal="识别变量依赖关系",
                        expected_answer="不能，因为 y=2-x。",
                        answer_checkpoints=["不能独立选择", "y=2-x"],
                        hint_ladder=["重新观察 x+y=2"],
                    )
                ],
            )
        ],
        final_answer="最小值为 2，当且仅当 x=y=1 时取得。",
        verification=["检验取等条件 x=y=1 满足 x+y=2"],
    )


class SolutionTests(unittest.TestCase):
    def test_solve_outcome_enforces_code_level_status_branches(self) -> None:
        solved = SolveOutcome(status="solved", solution=make_solution())
        self.assertIsNotNone(solved.solution)

        with self.assertRaises(ValidationError):
            SolveOutcome(status="incomplete")
        with self.assertRaises(ValidationError):
            SolveOutcome(
                status="ambiguous",
                solution=make_solution(),
                clarification_questions=["请说明变量范围。"],
            )

    def test_solution_rejects_unknown_fields(self) -> None:
        payload = make_solution().model_dump()
        payload["unexpected"] = True

        with self.assertRaises(ValidationError):
            Solution.model_validate(payload)

    def test_solution_references_current_lesson_plan(self) -> None:
        validate_solution_lesson_plan_references(
            make_solution(),
            load_lesson_plan("math"),
        )

    def test_unknown_lesson_plan_step_is_rejected(self) -> None:
        solution = make_solution()
        solution.steps[0].lesson_plan_step_id = "S99"

        with self.assertRaises(ValueError):
            validate_solution_lesson_plan_references(
                solution,
                load_lesson_plan("math"),
            )

    def test_solution_can_be_persisted_inside_teaching_state(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = TeachingStateRepository(
                Path(temp_directory) / "state.db"
            )
            state, lesson_plan = repository.get_or_create_with_lesson_plan(
                "problem_0"
            )
            solution = make_solution()
            state["original_problem"] = {
                "problem_statement": "已知 x+y=2，求 x²+y² 的最小值。",
                "status": "solved",
                "clarification_questions": [],
                "clarification_context": [],
            }
            state["solution"] = solution.model_dump(mode="json")
            state["problem_representation"] = {
                "schema_version": 1,
                "problem_id": "problem_test",
                "subject": "math",
                "goal_type": "extremum",
                "problem_type": "equation",
                "objects": ["x", "y"],
                "conditions": ["已知 x+y=2"],
                "goal": solution.goal,
                "structural_features": {"degrees_of_freedom": 2},
                "concept_ids": [
                    concept_id
                    for step in solution.steps
                    for concept_id in step.concept_ids
                ],
            }
            state["updated_at"] = datetime.now(timezone.utc).isoformat()

            repository.save(state, lesson_plan=lesson_plan)
            restored = repository.get("problem_0")

        self.assertEqual(
            restored["solution"]["steps"][0]["solution_step_id"],
            "step_0",
        )
        self.assertNotIn("current_solution_step_id", restored["teaching_progress"])

    def test_math_solver_uses_structured_solution_output(self) -> None:
        lesson_plan = load_lesson_plan("math")
        run_context = SimpleNamespace(
            context=MathSolverRunContext(lesson_plan=lesson_plan)
        )
        instruction = provide_math_solver_instructions(
            run_context,
            math_solution_agent,
        )

        if MATH_SOLUTION_USES_NATIVE_OUTPUT:
            self.assertIs(math_solution_agent.output_type, SolveOutcome)
        else:
            self.assertIsNone(math_solution_agent.output_type)
            self.assertIn("## JSON 文本兼容模式", instruction)
        self.assertIn("# 数学解题规划 Agent Instruction", instruction)
        self.assertIn("S3: 确定动静关系与控制参数", instruction)
        self.assertIn("数学解题理论上下文", instruction)

    def test_solver_input_is_student_independent_in_v02(self) -> None:
        payload = build_math_solver_input(
            "测试题目",
            {"status": {"current_step_confidence": "low"}},
        )

        self.assertIn('"problem_statement": "测试题目"', payload)
        self.assertNotIn('"current_step_confidence": "low"', payload)
        self.assertIn('"previous_solution": null', payload)
        self.assertIn('"revision_context": null', payload)
        self.assertIn(
            "# 数学解题规划 Agent Instruction",
            load_instruction("math_solver_instruction.md"),
        )

    def test_solver_revision_input_contains_previous_solution(self) -> None:
        previous_solution = make_solution().model_dump(mode="json")
        payload = json.loads(
            build_math_solver_input(
                "测试题目",
                revision_context={"summary": "修正第二步"},
                previous_solution=previous_solution,
            )
        )

        self.assertEqual(payload["previous_solution"], previous_solution)
        self.assertEqual(payload["revision_context"]["summary"], "修正第二步")

    def test_verifier_receives_only_its_solution_projection(self) -> None:
        payload = json.loads(
            build_solution_verifier_input(
                "已知 x+y=2，求最小值。",
                make_solution(),
                load_lesson_plan("math"),
            )
        )

        self.assertEqual(payload["origin_problem"], "已知 x+y=2，求最小值。")
        self.assertIn("relevant_context_sections", payload["lesson_plan"])
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("tutor_questions", serialized)
        self.assertNotIn("concept_ids", serialized)
        self.assertNotIn("likely_student_difficulties", serialized)


if __name__ == "__main__":
    unittest.main()
