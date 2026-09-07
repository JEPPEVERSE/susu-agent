"""v0.2 预计算与单轮教学执行编排。"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from agents import Runner

from susu_agent.agents.math_solver import (
    MathSolverRunContext,
    build_math_solver_input,
    math_solution_agent,
    validate_solution_lesson_plan_references,
)
from susu_agent.agents.solution_verifier import (
    SolutionVerifierRunContext,
    build_solution_verifier_input,
    solution_verifier_agent,
)
from susu_agent.agents.student_model_updater import (
    build_student_model_summarizer_input,
    student_model_summarizer_agent,
)
from susu_agent.agents.teaching_executor import (
    TeachingExecutorRunContext,
    build_teaching_executor_input,
    teaching_executor_agent,
)
from susu_agent.agents.teaching_planner import (
    TeachingPlannerRunContext,
    build_teaching_planner_input,
    teaching_planner_agent,
)
from susu_agent.agents.teaching_state_updater import (
    apply_teaching_execution,
    validate_teaching_execution_against_state,
)
from susu_agent.context_builder import ContextMessage
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.profiles import default_teacher_model
from susu_agent.repositories.student_model_repository import StudentModelRepository
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.solution import Solution
from susu_agent.schemas.teachers import validate_teacher_model
from susu_agent.schemas.v02 import (
    StudentModelPatch,
    TeachingExecution,
    TeachingStrategy,
    VerificationReport,
)
from susu_agent.structured_output import parse_structured_output


logger = logging.getLogger(__name__)


class V02Orchestrator:
    """按不同调用频率协调 v0.2 五层 Agent。"""

    def __init__(
        self,
        teaching_state_repository: TeachingStateRepository,
        student_model_repository: StudentModelRepository,
        *,
        student_id: str = "default_student",
        teacher_model: Mapping[str, Any] | None = None,
        grade: str = "unknown",
        max_solution_revisions: int | None = None,
    ) -> None:
        self.teaching_states = teaching_state_repository
        self.student_models = student_model_repository
        self.student_id = student_id
        self.grade = grade
        self.teacher_model = dict(teacher_model or default_teacher_model())
        validate_teacher_model(self.teacher_model)
        configured_revisions = int(os.getenv("MAX_SOLUTION_REVISIONS", "2"))
        self.max_solution_revisions = (
            configured_revisions
            if max_solution_revisions is None
            else max_solution_revisions
        )
        self.max_execution_repairs = max(
            0, int(os.getenv("MAX_EXECUTION_REPAIRS", "1"))
        )

    async def run_turn(
        self,
        session_id: str,
        current_user_message: str,
        recent_messages: Sequence[ContextMessage],
    ) -> tuple[str, dict[str, Any]]:
        state, lesson_plan = self.teaching_states.get_or_create_with_lesson_plan(
            session_id
        )
        student_model = self.student_models.get_or_create(
            self.student_id, self.grade
        )
        state = await self._ensure_problem_artifacts(
            current_user_message,
            state,
            lesson_plan,
            student_model,
        )
        execution = await self._execute(
            current_user_message,
            state,
            lesson_plan,
            student_model,
            recent_messages,
        )
        if execution.control_signal == "replan_required":
            state = apply_teaching_execution(state, execution)
            self.teaching_states.save(state, lesson_plan=lesson_plan)
            state = await self._plan(
                state, lesson_plan, student_model, force=True
            )
            execution = await self._execute(
                current_user_message,
                state,
                lesson_plan,
                student_model,
                recent_messages,
            )
        next_state = apply_teaching_execution(state, execution)
        self.teaching_states.save(next_state, lesson_plan=lesson_plan)
        return execution.response, next_state

    async def summarize_if_needed(self, session_id: str) -> bool:
        """在学生回复已经返回后执行低频长期模型总结。"""
        result = self.teaching_states.get_with_lesson_plan(session_id)
        if result is None:
            return False
        state, lesson_plan = result
        if (
            state["teaching_progress"]["stage"] != "complete"
            or state["v02_meta"]["summary_completed"]
        ):
            return False
        student_model = self.student_models.get_or_create(
            self.student_id, self.grade
        )
        await self._summarize(state, student_model, lesson_plan)
        return True

    async def _ensure_problem_artifacts(
        self,
        current_message: str,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
        student_model: Mapping[str, Any],
    ) -> dict[str, Any]:
        if "original_problem" not in state:
            state["original_problem"] = {
                "problem_statement": current_message.strip()
            }
        if state.get("solution") is None or state.get("verification_report") is None:
            state = await self._solve_and_verify(state, lesson_plan)
        if state.get("teaching_strategy") is None:
            state = await self._plan(state, lesson_plan, student_model)
        return state

    async def _solve_and_verify(
        self,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
    ) -> dict[str, Any]:
        problem = state["original_problem"]["problem_statement"]
        revision_context: dict[str, Any] | None = None
        for revision in range(self.max_solution_revisions + 1):
            result = await Runner.run(
                math_solution_agent,
                input=build_math_solver_input(
                    problem, revision_context=revision_context
                ),
                context=MathSolverRunContext(lesson_plan=lesson_plan),
            )
            solution = parse_structured_output(result.final_output, Solution)
            solution = Solution.model_validate(
                {**solution.model_dump(mode="json"), "problem_statement": problem}
            )
            validate_solution_lesson_plan_references(solution, lesson_plan)

            verification_result = await Runner.run(
                solution_verifier_agent,
                input=build_solution_verifier_input(problem, solution),
                context=SolutionVerifierRunContext(lesson_plan=lesson_plan),
            )
            report = parse_structured_output(
                verification_result.final_output, VerificationReport
            )
            self._validate_verification_references(report, solution)
            state["solution"] = solution.model_dump(mode="json")
            state["verification_report"] = report.model_dump(mode="json")
            state["v02_meta"]["solution_revision"] = revision
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.teaching_states.save(state, lesson_plan=lesson_plan)
            if report.verdict != "needs_revision":
                return state
            revision_context = report.model_dump(mode="json")
        raise RuntimeError("Solution could not pass verification within the revision limit.")

    async def _plan(
        self,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
        student_model: Mapping[str, Any],
        *,
        force: bool = False,
    ) -> dict[str, Any]:
        if state.get("teaching_strategy") is not None and not force:
            return state
        solution = Solution.model_validate(state["solution"])
        verification = VerificationReport.model_validate(
            state["verification_report"]
        )
        result = await Runner.run(
            teaching_planner_agent,
            input=build_teaching_planner_input(
                solution,
                verification,
                student_model,
                self.teacher_model,
                state,
            ),
            context=TeachingPlannerRunContext(lesson_plan=lesson_plan),
        )
        strategy = parse_structured_output(result.final_output, TeachingStrategy)
        self._validate_strategy_references(strategy, solution)
        state["teaching_strategy"] = strategy.model_dump(mode="json")
        state["teaching_progress"]["current_strategy_node_id"] = (
            strategy.initial_node_id
        )
        if strategy.initial_node_id is not None:
            first = next(
                node for node in strategy.nodes
                if node.node_id == strategy.initial_node_id
            )
            if first.solution_step_id is not None:
                state["teaching_progress"]["current_solution_step_id"] = (
                    first.solution_step_id
                )
                selected_step = next(
                    step
                    for step in solution.steps
                    if step.solution_step_id == first.solution_step_id
                )
                state["teaching_progress"]["current_lesson_plan_step_id"] = (
                    selected_step.lesson_plan_step_id
                )
            if first.solution_question_id is not None:
                state["teaching_progress"]["current_solution_question_id"] = (
                    first.solution_question_id
                )
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.teaching_states.save(state, lesson_plan=lesson_plan)
        return state

    async def _execute(
        self,
        current_user_message: str,
        state: Mapping[str, Any],
        lesson_plan: LessonPlanBundle,
        student_model: Mapping[str, Any],
        recent_messages: Sequence[ContextMessage],
    ) -> TeachingExecution:
        executor_input = build_teaching_executor_input(
            current_user_message,
            state,
            student_model,
            self.teacher_model,
            recent_messages,
        )
        last_error: ValueError | None = None
        for attempt in range(self.max_execution_repairs + 1):
            repair_input = executor_input
            if last_error is not None:
                repair_input += (
                    "\n\n上一次输出未通过运行时契约校验。请重新生成完整的 "
                    "TeachingExecution，不要解释错误。校验错误："
                    f"{last_error}"
                )
            result = await Runner.run(
                teaching_executor_agent,
                input=repair_input,
                context=TeachingExecutorRunContext(lesson_plan=lesson_plan),
            )
            try:
                execution = parse_structured_output(
                    result.final_output, TeachingExecution
                )
                validate_teaching_execution_against_state(state, execution)
                if attempt:
                    logger.warning(
                        "Teaching execution passed after %d repair attempt(s)",
                        attempt,
                    )
                return execution
            except (TypeError, ValueError) as error:
                last_error = error
                logger.warning(
                    "Rejected teaching execution artifact (attempt %d/%d): %s",
                    attempt + 1,
                    self.max_execution_repairs + 1,
                    error,
                )
        raise RuntimeError(
            "Teaching executor could not produce a state-consistent turn after "
            f"{self.max_execution_repairs + 1} attempt(s): {last_error}"
        ) from last_error

    async def _summarize(
        self,
        state: dict[str, Any],
        student_model: Mapping[str, Any],
        lesson_plan: LessonPlanBundle,
    ) -> None:
        if state["v02_meta"]["summary_completed"]:
            return
        result = await Runner.run(
            student_model_summarizer_agent,
            input=build_student_model_summarizer_input(state, student_model),
        )
        patch = parse_structured_output(result.final_output, StudentModelPatch)
        self.student_models.apply_patch(student_model, patch)
        state["v02_meta"]["summary_completed"] = True
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.teaching_states.save(state, lesson_plan=lesson_plan)

    @staticmethod
    def _validate_verification_references(
        report: VerificationReport, solution: Solution
    ) -> None:
        known = {step.solution_step_id for step in solution.steps}
        referenced = set(report.checked_solution_step_ids)
        referenced.update(
            step_id
            for issue in report.issues
            for step_id in issue.affected_solution_step_ids
        )
        unknown = referenced - known
        if unknown:
            raise ValueError(
                f"Verification references unknown Solution steps: {sorted(unknown)!r}."
            )
        if report.verdict == "passed" and set(report.checked_solution_step_ids) != known:
            raise ValueError(
                "A passed verification must check every Solution step exactly once."
            )

    @staticmethod
    def _validate_strategy_references(
        strategy: TeachingStrategy, solution: Solution
    ) -> None:
        known_steps = {step.solution_step_id for step in solution.steps}
        known_questions = {
            question.question_id
            for step in solution.steps
            for question in step.tutor_questions
        }
        unknown_steps = {
            node.solution_step_id
            for node in strategy.nodes
            if node.solution_step_id is not None
            and node.solution_step_id not in known_steps
        }
        unknown_questions = {
            node.solution_question_id
            for node in strategy.nodes
            if node.solution_question_id is not None
            and node.solution_question_id not in known_questions
        }
        if unknown_steps or unknown_questions:
            raise ValueError(
                "Teaching strategy references unknown Solution artifacts: "
                f"steps={sorted(unknown_steps)!r}, questions={sorted(unknown_questions)!r}."
            )
        if not strategy.nodes or strategy.initial_node_id is None:
            raise ValueError("A runnable teaching strategy requires an initial node.")
        question_owner = {
            question.question_id: step.solution_step_id
            for step in solution.steps
            for question in step.tutor_questions
        }
        mismatched_nodes = sorted(
            node.node_id
            for node in strategy.nodes
            if node.solution_question_id is not None
            and node.solution_step_id != question_owner[node.solution_question_id]
        )
        if mismatched_nodes:
            raise ValueError(
                "Teaching strategy nodes bind Solution questions to the wrong steps: "
                f"{mismatched_nodes!r}."
            )
        ungrounded_nodes = sorted(
            node.node_id
            for node in strategy.nodes
            if node.solution_question_id is None and not node.hint_ladder
        )
        if ungrounded_nodes:
            raise ValueError(
                "Every teaching strategy node needs a Solution question or planned hint: "
                f"{ungrounded_nodes!r}."
            )
