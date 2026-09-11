"""v0.3 五层 Agent 与记忆控制平面编排。"""

import json
import logging
import os
from hashlib import sha256
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
from susu_agent.memory.bootstrap import index_lesson_plan
from susu_agent.memory.card_catalog import index_memory_cards
from susu_agent.memory.coordinator import CrossDomainCoordinator
from susu_agent.memory.problem_parser import build_problem_representation
from susu_agent.memory.repositories import MemoryRepository
from susu_agent.memory.router import MemoryRouter
from susu_agent.memory.write_gate import MemoryWriteGate
from susu_agent.profiles import default_teacher_model
from susu_agent.repositories.student_model_repository import StudentModelRepository
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.schemas.solution import Solution, SolveOutcome
from susu_agent.schemas.memory import (
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MemoryUpdateProposal,
    Provenance,
    RetrievalQuery,
)
from susu_agent.schemas.problem_representation import ProblemRepresentation
from susu_agent.schemas.teachers import validate_teacher_model
from susu_agent.schemas.v03 import (
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


class V03Orchestrator:
    """协调 v0.3 五层 Agent、工作记忆与长期记忆控制平面。"""

    def __init__(
        self,
        teaching_state_repository: TeachingStateRepository,
        student_model_repository: StudentModelRepository,
        *,
        student_id: str = "default_student",
        teacher_model: Mapping[str, Any] | None = None,
        grade: str = "unknown",
        max_solution_revisions: int | None = None,
        memory_enabled: bool | None = None,
        memory_repository: MemoryRepository | None = None,
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
        configured_memory = os.getenv("MEMORY_ENABLED", "false").casefold() in {
            "1", "true", "yes", "on"
        }
        self.memory_enabled = configured_memory if memory_enabled is None else memory_enabled
        self.memory_repository = memory_repository
        self.memory_router: MemoryRouter | None = None
        self.memory_coordinator: CrossDomainCoordinator | None = None
        self.memory_write_gate: MemoryWriteGate | None = None
        if self.memory_enabled:
            self.memory_repository = self.memory_repository or MemoryRepository(
                os.getenv("MEMORY_DB_PATH", "data/memory.db")
            )
            self.memory_router = MemoryRouter(self.memory_repository)
            self.memory_coordinator = CrossDomainCoordinator(self.memory_router)
            self.memory_write_gate = MemoryWriteGate(self.memory_repository)

    async def run_turn(
        self,
        session_id: str,
        current_user_message: str,
        recent_messages: Sequence[ContextMessage],
    ) -> tuple[str, dict[str, Any]]:
        state, lesson_plan = self.teaching_states.get_or_create_with_lesson_plan(
            session_id
        )
        state.setdefault("v03_meta", {})["memory_enabled"] = self.memory_enabled
        if self.memory_repository is not None:
            index_lesson_plan(self.memory_repository, lesson_plan)
            index_memory_cards(self.memory_repository, lesson_plan)
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
            or state["v03_meta"]["summary_completed"]
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
        if state.get("problem_representation") is None:
            state["problem_representation"] = build_problem_representation(
                state["original_problem"]["problem_statement"],
                subject=lesson_plan.subject,
            ).model_dump(mode="json")
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
            solution_memory = (
                self._retrieve_solution_memory(state) if self.memory_enabled else None
            )
            solver_input = build_math_solver_input(
                solver_problem,
                revision_context=revision_context,
                previous_solution=previous_solution,
                problem_representation=(
                    state.get("problem_representation") if self.memory_enabled else None
                ),
                retrieved_solution_memory=solution_memory,
            )
            if self.memory_enabled:
                logger.debug("Attached v0.3 problem and retrieval projections to solver")
            outcome = await self._run_structured_agent(
                math_solution_agent,
                input=solver_input,
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
            representation = outcome.problem_representation or build_problem_representation(
                problem, subject=lesson_plan.subject, solution=solution
            )
            if representation.subject != lesson_plan.subject:
                raise ValueError("ProblemRepresentation subject does not match lesson plan.")
            state["problem_representation"] = representation.model_dump(mode="json")
            verifier_input = build_solution_verifier_input(
                solver_problem,
                solution,
                lesson_plan,
                problem_representation=representation,
            )
            report = await self._run_structured_agent(
                solution_verifier_agent,
                input=verifier_input,
                context=SolutionVerifierRunContext(lesson_plan=lesson_plan),
                output_type=VerificationReport,
                validator=lambda artifact: self._validate_verification_references(
                    artifact, solution, representation
                ),
            )
            state["solution"] = solution.model_dump(mode="json")
            state["verification_report"] = report.model_dump(mode="json")
            original_problem["status"] = "solved"
            original_problem["clarification_questions"] = []
            state["v03_meta"]["solution_revision"] = revision
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
        memory_context = self._retrieve_planning_memory(state, solution)
        strategy = await self._run_structured_agent(
            teaching_planner_agent,
            input=build_teaching_planner_input(
                solution,
                verification,
                student_model,
                self.teacher_model,
                state,
                subject_level_policy,
                memory_context,
            ),
            context=TeachingPlannerRunContext(lesson_plan=lesson_plan),
            output_type=TeachingStrategy,
            validator=lambda artifact: self._validate_strategy_references(
                artifact, solution, subject_level_policy, state
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
        self._record_strategy_memory_adoption(state, strategy)
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
        memory_context = self._retrieve_execution_memory(
            current_user_message, state
        )
        executor_input = build_teaching_executor_input(
            current_user_message,
            state,
            student_model,
            self.teacher_model,
            recent_messages,
            memory_context,
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
                self._record_execution_memory_adoption(state, execution)
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
        if state["v03_meta"]["summary_completed"]:
            return
        patch = await self._run_structured_agent(
            student_model_summarizer_agent,
            input=build_student_model_summarizer_input(state, student_model),
            context=None,
            output_type=StudentModelPatch,
        )
        self.student_models.apply_patch(student_model, patch)
        self._submit_memory_proposals(state, lesson_plan, patch)
        state["v03_meta"]["summary_completed"] = True
        state["updated_at"] = datetime.now(timezone.utc).isoformat()
        self.teaching_states.save(state, lesson_plan=lesson_plan)

    def _retrieve_planning_memory(
        self, state: dict[str, Any], solution: Solution
    ) -> dict[str, Any]:
        if self.memory_coordinator is None:
            return {}
        representation = ProblemRepresentation.model_validate(
            state["problem_representation"]
        )
        query = RetrievalQuery(
            subject=representation.subject,
            task_stage="plan_instruction",
            target_agent="teaching_planner",
            query_text=(
                f"{representation.goal}\n{solution.strategy_summary}"
            ),
            concept_ids=representation.concept_ids,
            lesson_plan_step_ids=list(
                dict.fromkeys(step.lesson_plan_step_id for step in solution.steps)
            ),
            memory_types=[
                MemoryType.QUESTION_CARD,
                MemoryType.LESSON_CHUNK,
                MemoryType.TEACHING_CASE,
            ],
            student_id=self.student_id,
            session_id=state["session_id"],
            goal_type=representation.goal_type,
            problem_type=representation.problem_type,
            structural_features=representation.structural_features,
        )
        result = self.memory_coordinator.retrieve(query)
        payload = result.model_dump(mode="json")
        state.setdefault("retrieval_cache", {})["planning"] = payload
        return {"result": payload, "evidence_prompt": result.to_prompt()}

    def _retrieve_solution_memory(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.memory_coordinator is None:
            return {}
        representation = ProblemRepresentation.model_validate(
            state["problem_representation"]
        )
        query = RetrievalQuery(
            subject=representation.subject,
            task_stage="solve",
            target_agent="solution_agent",
            query_text=(
                f"{representation.goal}\n类型：{representation.problem_type} "
                f"目标：{representation.goal_type}"
            ),
            concept_ids=representation.concept_ids,
            memory_types=[MemoryType.SOLUTION_PATTERN, MemoryType.LESSON_CHUNK],
            session_id=state["session_id"],
            goal_type=representation.goal_type,
            problem_type=representation.problem_type,
            structural_features=representation.structural_features,
            top_k=6,
            max_context_chars=4_000,
        )
        result = self.memory_coordinator.retrieve(query)
        payload = result.model_dump(mode="json")
        state.setdefault("retrieval_cache", {})["solution"] = payload
        return {"result": payload, "evidence_prompt": result.to_prompt()}

    def _retrieve_execution_memory(
        self, current_user_message: str, state: Mapping[str, Any]
    ) -> dict[str, Any]:
        if self.memory_coordinator is None:
            return {}
        representation = ProblemRepresentation.model_validate(
            state["problem_representation"]
        )
        progress = state.get("teaching_progress", {})
        current_node_id = progress.get("current_strategy_node_id")
        strategy = state.get("teaching_strategy") or {}
        current_node = next(
            (node for node in strategy.get("nodes", []) if node.get("node_id") == current_node_id),
            {},
        )
        solution = state.get("solution") or {}
        current_step = next(
            (
                step for step in solution.get("steps", [])
                if step.get("solution_step_id") == current_node.get("solution_step_id")
            ),
            {},
        )
        open_question = next(
            (
                item.get("question", "")
                for item in reversed(state.get("open_question_history", []))
                if item.get("status") == "open"
            ),
            "",
        )
        query = RetrievalQuery(
            subject=representation.subject,
            task_stage="assess_student_answer",
            target_agent="teaching_executor",
            query_text=(
                f"当前问题：{open_question}\n目标：{current_node.get('goal', '')}"
                f"\n学生回答：{current_user_message}"
            ),
            concept_ids=current_step.get("concept_ids", representation.concept_ids),
            lesson_plan_step_ids=(
                [current_step["lesson_plan_step_id"]]
                if current_step.get("lesson_plan_step_id") else []
            ),
            memory_types=[MemoryType.MISCONCEPTION_CARD],
            student_id=self.student_id,
            session_id=state["session_id"],
            goal_type=representation.goal_type,
            problem_type=representation.problem_type,
            structural_features=representation.structural_features,
            top_k=5,
            max_context_chars=3_000,
        )
        result = self.memory_coordinator.retrieve(query)
        if isinstance(state, dict):
            state.setdefault("retrieval_cache", {})["execution"] = result.model_dump(
                mode="json"
            )
        return {
            "current_question": open_question,
            "result": result.model_dump(mode="json"),
            "evidence_prompt": result.to_prompt(),
        }

    def _submit_memory_proposal(
        self, state: dict[str, Any], lesson_plan: LessonPlanBundle
    ) -> None:
        if self.memory_write_gate is None or not state.get("learning_evidence"):
            return
        evidence_ids = [
            item.get("evidence_id")
            for item in state["learning_evidence"]
            if isinstance(item, Mapping) and item.get("evidence_id")
        ]
        if not evidence_ids:
            return
        digest = sha256(
            f"{state['session_id']}:{','.join(evidence_ids)}".encode("utf-8")
        ).hexdigest()[:16]
        now = datetime.now(timezone.utc)
        candidate = MemoryItem(
            memory_id=f"teaching-case:{digest}",
            memory_type=MemoryType.TEACHING_CASE,
            canonical_text=json.dumps(
                {
                    "problem_representation": state.get("problem_representation"),
                    "strategy_summary": (state.get("teaching_strategy") or {}).get("summary"),
                    "learning_evidence": state["learning_evidence"],
                },
                ensure_ascii=False,
            ),
            retrieval_text=(
                f"{(state.get('teaching_strategy') or {}).get('summary', '')} "
                + " ".join(item.get("observation", "") for item in state["learning_evidence"])
            ),
            subject=lesson_plan.subject,
            task_stages=["plan_instruction"],
            target_agents=["teaching_planner", "student_model_summarizer"],
            concept_ids=list(
                (state.get("problem_representation") or {}).get("concept_ids", [])
            ),
            scope=MemoryScope.SUBJECT,
            provenance=Provenance(
                source_type="session_evidence",
                source_id=state["session_id"],
                evidence_ids=evidence_ids,
                created_by="student_model_summarizer",
            ),
            confidence=0.3,
            status=MemoryStatus.STAGING,
            created_at=now,
            updated_at=now,
        )
        proposal = MemoryUpdateProposal(
            proposal_id=f"proposal:{digest}",
            operation="add",
            candidate_content=candidate,
            supporting_evidence_ids=evidence_ids,
            evidence_source_ids=[state["session_id"]],
            proposed_confidence=0.3,
            scope=MemoryScope.SUBJECT,
            required_reviewers=["math", "duplicate_conflict", "pedagogy", "privacy"],
        )
        self.memory_write_gate.submit(proposal)
        state.setdefault("memory_update_proposal_ids", []).append(proposal.proposal_id)

    def _submit_memory_proposals(
        self,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
        patch: StudentModelPatch,
    ) -> None:
        if self.memory_write_gate is None:
            return
        submitted = 0
        allowed_evidence_ids = {
            item.get("evidence_id")
            for item in state.get("learning_evidence", [])
            if isinstance(item, Mapping) and item.get("evidence_id")
        }
        for proposal in patch.memory_update_proposals:
            if not set(proposal.supporting_evidence_ids).issubset(allowed_evidence_ids):
                raise ValueError("Memory proposal references evidence outside this session.")
            if set(proposal.evidence_source_ids) - {state["session_id"]}:
                raise ValueError("Memory proposal claims evidence from another session.")
            candidate = proposal.candidate_content
            if candidate is not None:
                if candidate.subject != lesson_plan.subject:
                    raise ValueError("Memory proposal subject does not match session.")
                if candidate.scope == MemoryScope.STUDENT and candidate.student_id != self.student_id:
                    raise ValueError("Memory proposal targets another student.")
            self.memory_write_gate.submit(proposal)
            if proposal.proposal_id not in state.setdefault(
                "memory_update_proposal_ids", []
            ):
                state["memory_update_proposal_ids"].append(proposal.proposal_id)
            submitted += 1
        if submitted == 0:
            self._submit_memory_proposal(state, lesson_plan)

    def _record_strategy_memory_adoption(
        self, state: dict[str, Any], strategy: TeachingStrategy
    ) -> None:
        if self.memory_router is None:
            return
        adopted = list(
            dict.fromkeys(
                [*strategy.retrieval_evidence_ids]
                + [
                    memory_id
                    for node in strategy.nodes
                    for memory_id in node.retrieval_evidence_ids
                ]
                + [
                    node.question_card_id
                    for node in strategy.nodes
                    if node.question_card_id is not None
                ]
            )
        )
        self.memory_router.record_adoption(adopted, session_id=state["session_id"])
        cache = state.get("retrieval_cache", {}).get("planning")
        if isinstance(cache, dict):
            cache["adopted_memory_ids"] = adopted

    def _record_execution_memory_adoption(
        self, state: Mapping[str, Any], execution: TeachingExecution
    ) -> None:
        if self.memory_router is None:
            return
        adopted = list(
            dict.fromkeys(
                [*execution.retrieval_evidence_ids]
                + execution.diagnosed_misconception_card_ids
                + [
                    memory_id
                    for evidence in execution.learning_evidence
                    for memory_id in (
                        evidence.retrieval_evidence_ids
                        + evidence.misconception_card_ids
                    )
                ]
            )
        )
        self.memory_router.record_adoption(adopted, session_id=state["session_id"])
        if isinstance(state, dict):
            cache = state.get("retrieval_cache", {}).get("execution")
            if isinstance(cache, dict):
                cache["adopted_memory_ids"] = adopted

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

    def _validate_solve_outcome(
        self, outcome: SolveOutcome, lesson_plan: LessonPlanBundle
    ) -> None:
        if outcome.solution is not None:
            validate_solution_lesson_plan_references(outcome.solution, lesson_plan)
        if (
            self.memory_enabled
            and outcome.status == "solved"
            and outcome.problem_representation is None
        ):
            raise ValueError("v0.3 solved outcomes require ProblemRepresentation.")
        if (
            outcome.problem_representation is not None
            and outcome.problem_representation.subject != lesson_plan.subject
        ):
            raise ValueError("ProblemRepresentation subject does not match lesson plan.")
        if outcome.solution is not None and outcome.problem_representation is not None:
            solution_concepts = {
                concept_id
                for step in outcome.solution.steps
                for concept_id in step.concept_ids
            }
            missing = solution_concepts - set(outcome.problem_representation.concept_ids)
            if missing:
                raise ValueError(
                    f"ProblemRepresentation omits Solution concepts: {sorted(missing)!r}."
                )

    @staticmethod
    def _validate_verification_references(
        report: VerificationReport,
        solution: Solution,
        representation: ProblemRepresentation,
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
        if report.verdict == "passed" and not report.evidence_sufficient:
            raise ValueError("A passed verification requires sufficient evidence.")
        if report.verdict == "passed" and representation.conditions:
            expected_conditions = set(range(len(representation.conditions)))
            if set(report.checked_condition_indices) != expected_conditions:
                raise ValueError(
                    "A passed verification must check every represented condition."
                )

    @staticmethod
    def _validate_strategy_references(
        strategy: TeachingStrategy,
        solution: Solution,
        subject_level_policy: Mapping[str, Any] | None = None,
        teaching_state: Mapping[str, Any] | None = None,
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
        planning_cache = (
            teaching_state.get("retrieval_cache", {}).get("planning", {})
            if teaching_state is not None else {}
        )
        retrieved = {
            item.get("memory_id"): item.get("memory_type")
            for item in planning_cache.get("evidence", [])
            if isinstance(item, Mapping)
        }
        referenced_memory_ids = {
            memory_id
            for node in strategy.nodes
            for memory_id in node.retrieval_evidence_ids
        } | set(strategy.retrieval_evidence_ids)
        referenced_memory_ids.update(
            node.question_card_id
            for node in strategy.nodes
            if node.question_card_id is not None
        )
        unknown_memory = referenced_memory_ids - set(retrieved)
        if unknown_memory:
            raise ValueError(
                f"Teaching strategy references unreturned memory: {sorted(unknown_memory)!r}."
            )
        invalid_cards = {
            node.question_card_id
            for node in strategy.nodes
            if node.question_card_id is not None
            and retrieved.get(node.question_card_id) != MemoryType.QUESTION_CARD.value
        }
        if invalid_cards:
            raise ValueError(
                f"Teaching nodes reference non-Question Cards: {sorted(invalid_cards)!r}."
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
            if entry_question_id is not None and initial_node.question_card_id is None and (
                initial_node.solution_question_id != entry_question_id
                or initial_node.solution_step_id != entry_step_id
            ):
                raise ValueError(
                    "Teaching strategy initial node must match the code-selected "
                    "subject-level entry question."
                )
            if initial_node.question_card_id is not None and (
                initial_node.solution_step_id != entry_step_id
            ):
                raise ValueError(
                    "A Question Card entry must preserve the code-selected Solution step."
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


# 旧调用方无需立即迁移导入路径。
V02Orchestrator = V03Orchestrator
