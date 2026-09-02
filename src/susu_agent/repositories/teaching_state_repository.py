import json
import sqlite3
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from susu_agent.lesson_plan_loader import LessonPlanBundle, LessonPlanLoader
from susu_agent.schemas.teaching_state import validate_teaching_state


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
            "schema_version": 3,
            "lesson_plan": TeachingStateRepository._lesson_plan_metadata(
                selected_lesson_plan
            ),
            "open_question_history": [],
            "teaching_progress": {
                "stage": "understand_task",
                "current_lesson_plan_step_id": None,
                "completed_lesson_plan_step_ids": [],
                "lesson_plan_step_summary": "",
                "hints_num": 0,
                "confirmed_steps": [],
                "next_teacher_action": "ask_question",
            },
            "student_model": {"status": {}},
            "updated_at": now,
            "memory_meta": {
                "last_processed_message_id": None,
                "last_compacted_message_id": None,
                "rolling_summary": "",
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
        elif schema_version != 3:
            raise ValueError(
                f"Unsupported teaching state schema_version: {schema_version!r}"
            )

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

        state["lesson_plan"] = self._lesson_plan_metadata(lesson_plan)
        state["schema_version"] = 3
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

        state["lesson_plan"] = self._lesson_plan_metadata(lesson_plan)
        state["schema_version"] = 3
        return state

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

    @classmethod
    def _validate_lesson_plan_references(
        cls,
        state: dict[str, Any],
        lesson_plan: LessonPlanBundle,
    ) -> None:
        if state.get("lesson_plan") != cls._lesson_plan_metadata(lesson_plan):
            raise ValueError("Teaching state lesson_plan metadata is stale.")

        allowed_step_ids = set(lesson_plan.step_ids)
        progress = state.get("teaching_progress", {})
        referenced_step_ids = [
            progress.get("current_lesson_plan_step_id"),
            *progress.get("completed_lesson_plan_step_ids", []),
            *(
                question.get("lesson_plan_step_id")
                for question in state.get("open_question_history", [])
            ),
        ]
        unknown_step_ids = sorted(
            {
                step_id
                for step_id in referenced_step_ids
                if step_id is not None and step_id not in allowed_step_ids
            }
        )
        if unknown_step_ids:
            raise ValueError(
                f"Teaching state references unknown lesson plan steps: "
                f"{unknown_step_ids!r}."
            )
