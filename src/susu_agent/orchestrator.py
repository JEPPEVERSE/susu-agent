"""v0.2 预计算与单轮教学执行编排。"""

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence, TypeVar

from agents import Runner
from pydantic import BaseModel

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
    build_subject_level_policy,
    build_teaching_planner_input,
    teaching_planner_agent,
)
from susu_agent.context_builder import ContextMessage
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.profiles import default_teacher_model
from susu_agent.repositories.student_model_repository import StudentModelRepository
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.solution import Solution, SolveOutcome
from susu_agent.schemas.teachers import validate_teacher_model
from susu_agent.schemas.v02 import (
    StudentModelPatch,
    TeachingExecution,
    TeachingStrategy,
    VerificationReport,
)
from susu_agent.teaching_runtime import (
    apply_teaching_execution,
    render_teaching_response,
    resolve_execution_decision,
    validate_strategy_runtime_contract,
    validate_teaching_execution_against_state,
)
from susu_agent.structured_output import parse_structured_output


logger = logging.getLogger(__name__)
StructuredArtifact = TypeVar("StructuredArtifact", bound=BaseModel)


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
        available_subjects = self.teaching_states.available_subjects()
        if self.teaching_states.default_subject not in available_subjects:
            raise ValueError(
                "Configured subject has no registered lesson plan: "
                f"{self.teaching_states.default_subject!r}."
            )
        self.subject = self.teaching_states.default_subject
        configured_revisions = int(os.getenv("MAX_SOLUTION_REVISIONS", "2"))
        self.max_solution_revisions = max(
            0,
            configured_revisions
            if max_solution_revisions is None
            else max_solution_revisions,
        )
        self.max_execution_repairs = max(
            0, int(os.getenv("MAX_EXECUTION_REPAIRS", "1"))
        )
        self.max_artifact_repairs = max(
            0, int(os.getenv("MAX_ARTIFACT_REPAIRS", "1"))
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
        if lesson_plan.subject != self.subject:
            raise ValueError("Session subject does not match the configured subject route.")
        student_model = self.student_models.get_or_create(
            self.student_id, self.grade
        )
        state, intake_response = await self._ensure_problem_artifacts(
            current_user_message,
            state,
            lesson_plan,
            student_model,
        )
        if intake_response is not None:
            return intake_response, state
        execution = await self._execute(
            current_user_message,
            state,
            lesson_plan,
            student_model,
            recent_messages,
        )
        decision = resolve_execution_decision(state, execution)
        if decision.control_signal == "replan_required":
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
        return render_teaching_response(execution), next_state

    async def summarize_if_needed(self, session_id: str) -> bool:
        """在学生回复已经返回后执行低频长期模型总结。"""
        result = self.teaching_states.get_with_lesson_plan(session_id)
        if result is None:
            return False
        state, lesson_plan = result
        if (
            state.get("teaching_strategy") is None
            or state["teaching_progress"]["current_strategy_node_id"] is not None
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
    ) -> tuple[dict[str, Any], str | None]:
        if "original_problem" not in state:
            state["original_problem"] = {
                "problem_statement": current_message.strip(),
                "status": "pending",
                "clarification_questions": [],
                "clarification_context": [],
            }
        report_data = state.get("verification_report")
        report_passed = (
            isinstance(report_data, Mapping)
            and report_data.get("verdict") == "passed"
        )
        if state.get("solution") is None or not report_passed:
            state, intake_response = await self._solve_and_verify(
                state, lesson_plan, current_message
            )
            if intake_response is not None:
                return state, intake_response
        if state.get("teaching_strategy") is None:
            state = await self._plan(state, lesson_plan, student_model)
        return state, None

    async def _solve_and_verify(
        self,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
        current_message: str,
    ) -> tuple[dict[str, Any], str | None]:
        original_problem = state["original_problem"]
        problem = original_problem["problem_statement"]
        if original_problem.get("status") in {"incomplete", "ambiguous"}:
            clarification_context = original_problem.setdefault(
                "clarification_context", []
            )
            normalized_message = current_message.strip()
            if (
                normalized_message
                and normalized_message != problem
                and normalized_message not in clarification_context
            ):
                clarification_context.append(normalized_message)
        context_items = original_problem.get("clarification_context", [])
        solver_problem = problem
        if context_items:
            solver_problem += "\n\n学生补充信息：\n" + "\n".join(
                f"- {item}" for item in context_items
            )
        revision_context: dict[str, Any] | None = None
        previous_solution: dict[str, Any] | None = None
        for revision in range(self.max_solution_revisions + 1):
            outcome = await self._run_structured_agent(
                math_solution_agent,
                input=build_math_solver_input(
                    solver_problem,
                    revision_context=revision_context,
                    previous_solution=previous_solution,
                ),
                context=MathSolverRunContext(lesson_plan=lesson_plan),
                output_type=SolveOutcome,
                validator=lambda artifact: self._validate_solve_outcome(
                    artifact, lesson_plan
                ),
            )
            if outcome.status != "solved":
                if revision_context is not None:
                    raise RuntimeError(
                        "A revision attempt unexpectedly returned an unresolved outcome."
                    )
                original_problem["status"] = outcome.status
                original_problem["clarification_questions"] = list(
                    outcome.clarification_questions
                )
                state["solution"] = None
                state["verification_report"] = None
                state["teaching_strategy"] = None
                state["updated_at"] = datetime.now(timezone.utc).isoformat()
                self.teaching_states.save(state, lesson_plan=lesson_plan)
                if outcome.clarification_questions:
                    response = "在继续求解前，我需要确认：" + outcome.clarification_questions[0]
                else:
                    response = outcome.reason or "当前题目不属于已加载教案支持的范围。"
                return state, response
            solution = outcome.solution
            if solution is None:  # SolveOutcome 已校验，此分支仅用于类型收窄。
                raise RuntimeError("Solved outcome did not contain a Solution.")
            report = await self._run_structured_agent(
                solution_verifier_agent,
                input=build_solution_verifier_input(
                    solver_problem, solution, lesson_plan
                ),
                context=SolutionVerifierRunContext(lesson_plan=lesson_plan),
                output_type=VerificationReport,
                validator=lambda artifact: self._validate_verification_references(
                    artifact, solution
                ),
            )
            state["solution"] = solution.model_dump(mode="json")
            state["verification_report"] = report.model_dump(mode="json")
            original_problem["status"] = "solved"
            original_problem["clarification_questions"] = []
            state["v02_meta"]["solution_revision"] = revision
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.teaching_states.save(state, lesson_plan=lesson_plan)
            if report.verdict == "passed":
                return state, None
            previous_solution = solution.model_dump(mode="json")
            revision_context = report.model_dump(mode="json")
        raise RuntimeError(
            "Solution verification remained needs_revision after "
            f"{self.max_solution_revisions + 1} attempt(s): {report.summary}"
        )

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
        subject_level_policy = build_subject_level_policy(
            solution, student_model, lesson_plan.subject
        )
        strategy = await self._run_structured_agent(
            teaching_planner_agent,
            input=build_teaching_planner_input(
                solution,
                verification,
                student_model,
                self.teacher_model,
                state,
                subject_level_policy,
            ),
            context=TeachingPlannerRunContext(lesson_plan=lesson_plan),
            output_type=TeachingStrategy,
            validator=lambda artifact: self._validate_strategy_references(
                artifact, solution, subject_level_policy
            ),
        )
        state["teaching_strategy"] = strategy.model_dump(mode="json")
        state["teaching_progress"]["current_strategy_node_id"] = (
            strategy.initial_node_id
        )
        state["teaching_progress"]["completed_strategy_node_ids"] = []
        state["teaching_progress"]["satisfied_checkpoint_ids"] = []
        state["teaching_progress"]["attempts_by_node"] = {}
        state["teaching_progress"]["hint_indices_by_node"] = {}
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
        patch = await self._run_structured_agent(
            student_model_summarizer_agent,
            input=build_student_model_summarizer_input(state, student_model),
            context=None,
            output_type=StudentModelPatch,
        )
        self.student_models.apply_patch(student_model, patch)
        state["v02_meta"]["summary_completed"] = True
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.teaching_states.save(state, lesson_plan=lesson_plan)

    async def _run_structured_agent(
        self,
        agent: Any,
        *,
        input: str,
        context: Any,
        output_type: type[StructuredArtifact],
        validator: Callable[[StructuredArtifact], None] | None = None,
    ) -> StructuredArtifact:
        """统一纠正一次性 Agent 的 Schema 与 artifact 引用契约偏差。"""
        last_error: TypeError | ValueError | None = None
        for attempt in range(self.max_artifact_repairs + 1):
            repair_input = input
            if last_error is not None:
                repair_input += (
                    "\n\n上一次输出未通过结构化 Schema 校验或运行时契约校验。"
                    "请根据以下错误重新生成"
                    "完整且更紧凑的 JSON，不要解释；总长度控制在 10000 个字符以内："
                    f"{last_error}"
                )
            result = await Runner.run(agent, input=repair_input, context=context)
            try:
                artifact = parse_structured_output(result.final_output, output_type)
                if validator is not None:
                    validator(artifact)
                if attempt:
                    logger.warning(
                        "%s passed schema validation after %d repair attempt(s)",
                        agent.name,
                        attempt,
                    )
                return artifact
            except (TypeError, ValueError) as error:
                last_error = error
                logger.warning(
                    "Rejected %s artifact (attempt %d/%d): %s",
                    agent.name,
                    attempt + 1,
                    self.max_artifact_repairs + 1,
                    error,
                )
        raise RuntimeError(
            f"{agent.name} could not produce valid {output_type.__name__} after "
            f"{self.max_artifact_repairs + 1} attempt(s): {last_error}"
        ) from last_error

    @staticmethod
    def _validate_solve_outcome(
        outcome: SolveOutcome, lesson_plan: LessonPlanBundle
    ) -> None:
        if outcome.solution is not None:
            validate_solution_lesson_plan_references(outcome.solution, lesson_plan)

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
        strategy: TeachingStrategy,
        solution: Solution,
        subject_level_policy: Mapping[str, Any] | None = None,
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
        validate_strategy_runtime_contract(strategy)
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
        if subject_level_policy is not None:
            entry_question_id = subject_level_policy.get(
                "recommended_entry_question_id"
            )
            entry_step_id = subject_level_policy.get(
                "recommended_entry_solution_step_id"
            )
            initial_node = next(
                node
                for node in strategy.nodes
                if node.node_id == strategy.initial_node_id
            )
            if entry_question_id is not None and (
                initial_node.solution_question_id != entry_question_id
                or initial_node.solution_step_id != entry_step_id
            ):
                raise ValueError(
                    "Teaching strategy initial node must match the code-selected "
                    "subject-level entry question."
                )
        unknown_difficulty_steps = sorted(
            {
                step_id
                for difficulty in strategy.anticipated_difficulties
                for step_id in difficulty.related_solution_step_ids
                if step_id not in known_steps
            }
        )
        if unknown_difficulty_steps:
            raise ValueError(
                "Teaching strategy difficulties reference unknown Solution steps: "
                f"{unknown_difficulty_steps!r}."
            )
