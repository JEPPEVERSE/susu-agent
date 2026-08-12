import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from susu_agent.schemas.teaching_state import validate_teaching_state

class TeachingStateRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
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

        state = json.loads(row[0])
        validate_teaching_state(state)
        return state

    def get_or_create(self, session_id: str) -> dict[str, Any]:
        """读取指定会话的教学状态；不存在时创建初始状态。"""
        state = self.get(session_id)
        if state is not None:
            return state

        state = self.create_initial_state(session_id)
        self.save(state)
        return state

    @staticmethod
    def create_initial_state(session_id: str) -> dict[str, Any]:
        """构造一个符合 Schema 的初始教学状态。"""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "session_id": session_id,
            "schema_version": 1,
            "open_question_history": [],
            "teaching_progress": {
                "stage": "understand_problem",
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

    def save(self, state: dict[str, Any]) -> None:
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
