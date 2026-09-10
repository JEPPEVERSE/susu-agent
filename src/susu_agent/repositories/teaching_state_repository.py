import json
import logging
import re
import sqlite3
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from susu_agent.lesson_plan_loader import LessonPlanBundle, LessonPlanLoader
from susu_agent.schemas.solution import Solution
from susu_agent.schemas.teaching_state import validate_teaching_state
from susu_agent.schemas.v02 import LearningEvidence, TeachingStrategy, VerificationReport
from susu_agent.teaching_runtime import validate_strategy_runtime_contract


logger = logging.getLogger(__name__)


class TeachingStateRepository:
    def __init__(
        self,
        db_path: str | Path,
        default_subject: str = "math",
        lesson_plan_loader: LessonPlanLoader | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._default_subject = default_subject
        self._lesson_plan_loader = lesson_plan_loader or LessonPlanLoader()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize_table()
        logger.debug("Initialized teaching state repository at %s", self._db_path)

    @property
    def default_subject(self) -> str:
        """返回由应用配置、在任何 Agent 运行前确定的学科路由。"""
        return self._default_subject

    def available_subjects(self) -> tuple[str, ...]:
        return self._lesson_plan_loader.list_subjects()

    def _initialize_table(self) -> None:
        with closing(sqlite3.connect(self._db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS teaching_states (
                        session_id TEXT PRIMARY KEY,
                        schema_version INTEGER NOT NULL,
                        state_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

    def get(self, session_id: str) -> dict[str, Any] | None:
        result = self.get_with_lesson_plan(session_id)
        return result[0] if result is not None else None

    def get_with_lesson_plan(
        self,
        session_id: str,
    ) -> tuple[dict[str, Any], LessonPlanBundle] | None:
        """一次读取并返回状态及其对应的教案快照。"""
        with closing(sqlite3.connect(self._db_path)) as connection:
            row = connection.execute(
                """
                SELECT state_json
                FROM teaching_states
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()

        if row is None:
            logger.debug("No teaching state found for session %s", session_id)
            return None

        stored_state = json.loads(row[0])
        subject = (
            self._default_subject
            if stored_state.get("schema_version") == 1
            else stored_state.get("lesson_plan", {}).get(
                "subject",
                self._default_subject,
            )
        )
        lesson_plan = self._lesson_plan_loader.load(subject)
        state = self._upgrade_and_sync(stored_state, lesson_plan)
        if state != stored_state:
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
        validate_teaching_state(state)
        if state != stored_state:
            self.save(state, lesson_plan=lesson_plan)
            logger.info("Migrated teaching state for session %s", session_id)
        return state, lesson_plan

    def get_or_create(self, session_id: str) -> dict[str, Any]:
        """读取指定会话的教学状态；不存在时创建初始状态。"""
        state, _ = self.get_or_create_with_lesson_plan(session_id)
        return state

    def get_or_create_with_lesson_plan(
        self,
        session_id: str,
    ) -> tuple[dict[str, Any], LessonPlanBundle]:
        """读取或创建状态，并共享本轮唯一的教案快照。"""
        result = self.get_with_lesson_plan(session_id)
        if result is not None:
            return result

        lesson_plan = self._lesson_plan_loader.load(self._default_subject)
        logger.info("Creating initial teaching state for session %s", session_id)
        state = self.create_initial_state(
            session_id,
            lesson_plan=lesson_plan,
        )
        self.save(state, lesson_plan=lesson_plan)
        return state, lesson_plan

    @staticmethod
    def create_initial_state(
        session_id: str,
        subject: str = "math",
        lesson_plan_loader: LessonPlanLoader | None = None,
        lesson_plan: LessonPlanBundle | None = None,
    ) -> dict[str, Any]:
        """构造一个符合 Schema 的初始教学状态。"""
        now = datetime.now(timezone.utc).isoformat()
        selected_lesson_plan = lesson_plan or (
            lesson_plan_loader or LessonPlanLoader()
        ).load(subject)
        return {
            "session_id": session_id,
            "schema_version": 7,
            "lesson_plan": TeachingStateRepository._lesson_plan_metadata(
                selected_lesson_plan
            ),
            "solution": None,
            "verification_report": None,
            "teaching_strategy": None,
            "learning_evidence": [],
            "open_question_history": [],
            "teaching_progress": {
                "current_strategy_node_id": None,
                "completed_strategy_node_ids": [],
                "satisfied_checkpoint_ids": [],
                "attempts_by_node": {},
                "hint_indices_by_node": {},
            },
            "updated_at": now,
            "conversation_summary": "",
            "v02_meta": {
                "architecture_version": "0.2",
                "solution_revision": 0,
                "summary_completed": False,
            },
            "personal_ai": {
                "principal_id": None,
                "consent_scope": [],
                "data_classification": "personal",
                "encryption_ref": None,
            },
        }

    def _upgrade_and_sync(
        self,
        stored_state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
    ) -> dict[str, Any]:
        """把旧状态升级到当前 Schema，并同步由应用维护的教案元数据。"""
        state = deepcopy(stored_state)
        schema_version = state.get("schema_version")
        if schema_version == 1:
            state = self._upgrade_v1_state(state, lesson_plan)
        elif schema_version == 2:
            state = self._upgrade_v2_state(state, lesson_plan)
        elif schema_version == 3:
            state = self._upgrade_v3_state(state)
        elif schema_version == 4:
            state = self._upgrade_v4_state(state)
        elif schema_version not in {5, 6, 7}:
            raise ValueError(
                f"Unsupported teaching state schema_version: {schema_version!r}"
            )

        if state.get("schema_version") == 5:
            state = self._upgrade_v5_state(state)
        if state.get("schema_version") == 6:
            state = self._upgrade_v6_state(state)

        state["lesson_plan"] = self._lesson_plan_metadata(lesson_plan)
        return state

    def _upgrade_v1_state(
        self,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
    ) -> dict[str, Any]:
        """兼容升级尚未记录 lesson plan 的既有会话。"""
        stage_mapping = {
            "understand_problem": "understand_task",
            "recall_knowledge": "recall_knowledge",
            "make_plan": "make_plan",
            "solve": "execute",
            "verify": "verify",
            "complete": "complete",
        }
        progress = state.setdefault("teaching_progress", {})
        progress["stage"] = stage_mapping.get(
            progress.get("stage"),
            "understand_task",
        )
        progress.setdefault("current_lesson_plan_step_id", None)
        progress.setdefault("completed_lesson_plan_step_ids", [])
        progress.setdefault("lesson_plan_step_summary", "")

        for question in state.setdefault("open_question_history", []):
            question["stage"] = stage_mapping.get(
                question.get("stage"),
                "understand_task",
            )
            question.setdefault("lesson_plan_step_id", None)
            question.setdefault("solution_step_id", None)

        state["lesson_plan"] = self._lesson_plan_metadata(lesson_plan)
        self._add_solution_fields(state)
        self._add_v02_fields(state)
        state["schema_version"] = 5
        return state

    def _upgrade_v2_state(
        self,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
    ) -> dict[str, Any]:
        """把自由文本教案步骤迁移为清单中的稳定 step_id。"""
        progress = state.setdefault("teaching_progress", {})
        legacy_current = progress.pop("current_lesson_plan_step", None)
        legacy_completed = progress.pop("completed_lesson_plan_steps", [])
        progress["current_lesson_plan_step_id"] = self._resolve_legacy_step_id(
            legacy_current,
            lesson_plan,
        )
        progress["completed_lesson_plan_step_ids"] = [
            step_id
            for value in legacy_completed
            if (
                step_id := self._resolve_legacy_step_id(value, lesson_plan)
            )
            is not None
        ]

        for question in state.setdefault("open_question_history", []):
            legacy_step = question.pop("lesson_plan_step", None)
            question["lesson_plan_step_id"] = self._resolve_legacy_step_id(
                legacy_step,
                lesson_plan,
            )
            question.setdefault("solution_step_id", None)

        state["lesson_plan"] = self._lesson_plan_metadata(lesson_plan)
        self._add_solution_fields(state)
        self._add_v02_fields(state)
        state["schema_version"] = 5
        return state

    def _upgrade_v3_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """为既有教案状态加入题目级 Solution 和执行游标。"""
        self._add_solution_fields(state)
        self._add_v02_fields(state)
        state["schema_version"] = 5
        return state

    def _upgrade_v4_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """为 v0.1 状态加入 v0.2 artifact、执行游标与身份预留。"""
        self._add_v02_fields(state)
        state["schema_version"] = 5
        return state

    @staticmethod
    def _upgrade_v5_state(state: dict[str, Any]) -> dict[str, Any]:
        """迁移旧 Solution 字段，并把题目判定提升为代码拥有的状态。"""
        original = state.get("original_problem")
        solution = state.get("solution")
        legacy_status = solution.get("problem_status") if isinstance(solution, dict) else None
        status_mapping = {
            "solvable": "solved",
            "incomplete": "incomplete",
            "ambiguous": "ambiguous",
            "not_math": "unsupported",
        }
        if isinstance(original, dict):
            original.setdefault(
                "status",
                status_mapping.get(legacy_status, "solved" if solution else "pending"),
            )
            original.setdefault(
                "clarification_questions",
                list(solution.get("clarification_questions", []))
                if isinstance(solution, dict)
                else [],
            )
            original.setdefault("clarification_context", [])

        if isinstance(solution, dict) and solution.get("schema_version") == 1:
            solution["schema_version"] = 2
            for field in (
                "subject",
                "problem_statement",
                "problem_status",
                "clarification_questions",
                "knowledge_points",
                "likely_student_difficulties",
            ):
                solution.pop(field, None)
            for step in solution.get("steps", []):
                legacy_concepts = step.pop("knowledge_points", [])
                step["concept_ids"] = [
                    value
                    for value in legacy_concepts
                    if isinstance(value, str)
                    and re.fullmatch(r"[a-z][a-z0-9_]*", value)
                ]

        # Verifier 与 TeachingPlanner 的职责及上下文契约均已改变。旧 artifact
        # 即使标记为 passed 也不能作为新契约下的缓存命中；保留 Solution，下一轮
        # 按 v0.2 schema 重新验证并规划。
        has_cached_problem_artifacts = any(
            value is not None
            for value in (
                solution,
                state.get("verification_report"),
                state.get("teaching_strategy"),
            )
        )
        state["verification_report"] = None
        state["teaching_strategy"] = None
        if has_cached_problem_artifacts:
            progress = state.setdefault("teaching_progress", {})
            progress["stage"] = "understand_task"
            progress["current_strategy_node_id"] = None
            progress["current_solution_step_id"] = None
            progress["current_solution_question_id"] = None
            progress["open_question"] = None
            state["open_question_history"] = [
                question
                for question in state.get("open_question_history", [])
                if question.get("status") != "open"
            ]

        state["schema_version"] = 6
        return state

    @staticmethod
    def _upgrade_v6_state(state: dict[str, Any]) -> dict[str, Any]:
        """迁移到 v0.2 单一状态源：移除学生模型副本和派生游标。"""
        # v6 策略没有检查点累积和有限重试契约。继续复用可能保留
        # correct 自循环，因此只保留已验证解法，下一轮重新规划策略。
        if state.get("teaching_strategy") is not None:
            state["teaching_strategy"] = None
            state["open_question_history"] = []
            state.setdefault("teaching_progress", {})[
                "current_strategy_node_id"
            ] = None
        strategy = state.get("teaching_strategy") or {}
        nodes = strategy.get("nodes", []) if isinstance(strategy, dict) else []
        node_by_id = {
            node.get("node_id"): node
            for node in nodes
            if isinstance(node, dict) and node.get("node_id") is not None
        }
        nodes_by_question: dict[str, list[str]] = {}
        for node_id, node in node_by_id.items():
            question_id = node.get("solution_question_id")
            if question_id is not None:
                nodes_by_question.setdefault(question_id, []).append(node_id)

        old_progress = state.get("teaching_progress", {})
        current_node_id = old_progress.get("current_strategy_node_id")
        completed_solution_steps = set(
            old_progress.get("completed_solution_step_ids", [])
        )
        completed_solution_questions = set(
            old_progress.get("completed_solution_question_ids", [])
        )
        completed_nodes = [
            node_id
            for node_id, node in node_by_id.items()
            if (
                node.get("solution_question_id") in completed_solution_questions
                or (
                    node.get("solution_question_id") is None
                    and node.get("solution_step_id") in completed_solution_steps
                )
            )
        ]

        migrated_history: list[dict[str, Any]] = []
        attempts_by_node: dict[str, int] = {}
        for question in state.get("open_question_history", []):
            solution_question_id = question.get("solution_question_id")
            candidate_nodes = nodes_by_question.get(solution_question_id, [])
            strategy_node_id = (
                current_node_id
                if current_node_id in candidate_nodes
                else candidate_nodes[0] if candidate_nodes else None
            )
            old_assessment = question.get("agent_assessment", {})
            status = question.get("status", "abandoned")
            assessment = old_assessment.get("understanding", "not_answered")
            assessment_reason = old_assessment.get("summary", "")
            if status == "answered" and assessment == "not_answered":
                assessment = "unclear"
                assessment_reason = assessment_reason or "旧状态未记录明确判定。"
            if status != "answered":
                assessment = "not_answered"
                assessment_reason = ""
            checkpoint_count = len(
                node_by_id.get(strategy_node_id, {}).get("answer_checkpoints", [])
            )
            migrated_history.append(
                {
                    "question_id": question["question_id"],
                    "question": question["question"],
                    "strategy_node_id": strategy_node_id,
                    "solution_question_id": solution_question_id,
                    "target_checkpoint_indices": list(range(checkpoint_count)),
                    "status": status,
                    "asked_at": question["asked_at"],
                    "student_answer_summary": question.get("student_answer_summary"),
                    "assessment": assessment,
                    "assessment_reason": assessment_reason,
                    "resolved_at": question.get("resolved_at"),
                }
            )
            if status == "answered" and strategy_node_id is not None:
                attempts_by_node[strategy_node_id] = (
                    attempts_by_node.get(strategy_node_id, 0) + 1
                )

        state["open_question_history"] = migrated_history
        state["teaching_progress"] = {
            "current_strategy_node_id": current_node_id,
            "completed_strategy_node_ids": completed_nodes,
            "satisfied_checkpoint_ids": [],
            "attempts_by_node": attempts_by_node,
            "hint_indices_by_node": {},
        }
        state["conversation_summary"] = state.get("memory_meta", {}).get(
            "rolling_summary", ""
        )
        state.pop("memory_meta", None)
        state.pop("student_model", None)
        state["schema_version"] = 7
        return state

    @staticmethod
    def _add_solution_fields(state: dict[str, Any]) -> None:
        state.setdefault("solution", None)
        progress = state.setdefault("teaching_progress", {})
        progress.setdefault("current_solution_step_id", None)
        progress.setdefault("completed_solution_step_ids", [])
        progress.setdefault("solution_step_summary", "")
        progress.setdefault("current_solution_question_id", None)
        progress.setdefault("completed_solution_question_ids", [])
        for question in state.setdefault("open_question_history", []):
            question.setdefault("solution_step_id", None)
            question.setdefault("solution_question_id", None)

    @staticmethod
    def _add_v02_fields(state: dict[str, Any]) -> None:
        state.setdefault("verification_report", None)
        state.setdefault("teaching_strategy", None)
        state.setdefault("learning_evidence", [])
        state.setdefault("teaching_progress", {}).setdefault(
            "current_strategy_node_id", None
        )
        state.setdefault(
            "v02_meta",
            {"architecture_version": "0.2", "solution_revision": 0, "summary_completed": False},
        )
        state.setdefault(
            "personal_ai",
            {
                "principal_id": None,
                "consent_scope": [],
                "data_classification": "personal",
                "encryption_ref": None,
            },
        )

    @staticmethod
    def _resolve_legacy_step_id(
        value: Any,
        lesson_plan: LessonPlanBundle,
    ) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip()
        for step in lesson_plan.steps:
            if normalized in {step.step_id, step.name, step.label}:
                return step.step_id
        prefix = normalized.split(maxsplit=1)[0]
        return prefix if prefix in lesson_plan.step_ids else None

    @staticmethod
    def _lesson_plan_metadata(
        lesson_plan: LessonPlanBundle,
    ) -> dict[str, Any]:
        return {
            "subject": lesson_plan.subject,
            "manifest_schema_version": lesson_plan.manifest_schema_version,
            "lesson_plan_version": lesson_plan.lesson_plan_version,
            "step_ids": list(lesson_plan.step_ids),
            "instruction_sources": list(lesson_plan.instruction_sources),
            "context_sources": list(lesson_plan.context_sources),
            "content_digest": lesson_plan.content_digest,
        }

    def save(
        self,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle | None = None,
    ) -> None:
        selected_lesson_plan = lesson_plan or self._lesson_plan_loader.load(
            state["lesson_plan"]["subject"]
        )
        self._validate_lesson_plan_references(state, selected_lesson_plan)
        self._validate_v02_artifacts(state)
        validate_teaching_state(state)

        with closing(sqlite3.connect(self._db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO teaching_states (
                        session_id,
                        schema_version,
                        state_json,
                        updated_at
                    )
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        schema_version = excluded.schema_version,
                        state_json = excluded.state_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        state["session_id"],
                        state["schema_version"],
                        json.dumps(state, ensure_ascii=False),
                        state["updated_at"],
                    ),
                )
        logger.debug("Saved teaching state for session %s", state["session_id"])

    @staticmethod
    def _validate_v02_artifacts(state: dict[str, Any]) -> None:
        solution_data = state.get("solution")
        solution = Solution.model_validate(solution_data) if solution_data is not None else None
        problem_status = state.get("original_problem", {}).get("status")
        if solution is not None and problem_status != "solved":
            raise ValueError("A Solution artifact requires problem status 'solved'.")
        if problem_status in {"incomplete", "ambiguous", "unsupported"} and any(
            state.get(field) is not None
            for field in ("solution", "verification_report", "teaching_strategy")
        ):
            raise ValueError("An unresolved problem cannot contain downstream artifacts.")
        report_data = state.get("verification_report")
        if report_data is not None:
            report = VerificationReport.model_validate(report_data)
            if solution is None:
                raise ValueError("Verification report requires a Solution artifact.")
            known_steps = {step.solution_step_id for step in solution.steps}
            if report.verdict == "passed" and set(report.checked_solution_step_ids) != known_steps:
                raise ValueError("A passed verification must check every Solution step.")
        strategy_data = state.get("teaching_strategy")
        if strategy_data is not None:
            if solution is None or report_data is None:
                raise ValueError(
                    "Teaching strategy requires Solution and VerificationReport artifacts."
                )
            strategy = TeachingStrategy.model_validate(strategy_data)
            validate_strategy_runtime_contract(strategy)
            known_steps = {step.solution_step_id for step in solution.steps}
            question_owner = {
                question.question_id: step.solution_step_id
                for step in solution.steps
                for question in step.tutor_questions
            }
            for node in strategy.nodes:
                if node.solution_step_id is not None and node.solution_step_id not in known_steps:
                    raise ValueError("Teaching strategy references an unknown Solution step.")
                if node.solution_question_id is not None:
                    if node.solution_question_id not in question_owner:
                        raise ValueError(
                            "Teaching strategy references an unknown Solution question."
                        )
                    if question_owner[node.solution_question_id] != node.solution_step_id:
                        raise ValueError(
                            "Teaching strategy binds a Solution question to the wrong step."
                        )
            unknown_difficulty_steps = {
                step_id
                for difficulty in strategy.anticipated_difficulties
                for step_id in difficulty.related_solution_step_ids
                if step_id not in known_steps
            }
            if unknown_difficulty_steps:
                raise ValueError(
                    "Teaching strategy difficulties reference unknown Solution steps."
                )
            current_node_id = state.get("teaching_progress", {}).get(
                "current_strategy_node_id"
            )
            known_node_ids = {node.node_id for node in strategy.nodes}
            if current_node_id is not None and current_node_id not in known_node_ids:
                raise ValueError("Teaching state references an unknown strategy node.")
            progress = state.get("teaching_progress", {})
            unknown_completed_nodes = set(
                progress.get("completed_strategy_node_ids", [])
            ) - known_node_ids
            if unknown_completed_nodes:
                raise ValueError("Teaching state completed unknown strategy nodes.")
            for checkpoint_id in progress.get("satisfied_checkpoint_ids", []):
                node_id, raw_index = checkpoint_id.split(":checkpoint_", 1)
                node = next(
                    (item for item in strategy.nodes if item.node_id == node_id),
                    None,
                )
                if node is None or int(raw_index) >= len(node.answer_checkpoints):
                    raise ValueError(
                        "Teaching state references an unknown strategy checkpoint."
                    )
        for item in state.get("learning_evidence", []):
            LearningEvidence.model_validate(item)

    @classmethod
    def _validate_lesson_plan_references(
        cls,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
    ) -> None:
        if state.get("lesson_plan") != cls._lesson_plan_metadata(lesson_plan):
            raise ValueError("Teaching state lesson_plan metadata is stale.")

        allowed_step_ids = set(lesson_plan.step_ids)
        solution_data = state.get("solution")
        if solution_data is None:
            solution_step_ids: set[str] = set()
            solution_question_ids: set[str] = set()
        else:
            solution = Solution.model_validate(solution_data)
            unknown_solution_lesson_steps = sorted(
                {
                    step.lesson_plan_step_id
                    for step in solution.steps
                    if step.lesson_plan_step_id not in allowed_step_ids
                }
            )
            if unknown_solution_lesson_steps:
                raise ValueError(
                    "Solution references unknown lesson plan steps: "
                    f"{unknown_solution_lesson_steps!r}."
                )
            solution_step_ids = {
                step.solution_step_id for step in solution.steps
            }
            solution_question_ids = {
                question.question_id
                for step in solution.steps
                for question in step.tutor_questions
            }

        referenced_solution_question_ids = [
            *(
                question.get("solution_question_id")
                for question in state.get("open_question_history", [])
            ),
        ]
        unknown_solution_question_ids = sorted(
            {
                question_id
                for question_id in referenced_solution_question_ids
                if question_id is not None
                and question_id not in solution_question_ids
            }
        )
        if unknown_solution_question_ids:
            raise ValueError(
                "Teaching state references unknown Solution questions: "
                f"{unknown_solution_question_ids!r}."
            )
