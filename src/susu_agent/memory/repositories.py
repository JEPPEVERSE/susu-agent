"""SQLite 权威记忆记录与可重建检索投影。"""

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from susu_agent.schemas.memory import (
    MemoryItem,
    MemoryStatus,
    MemoryUpdateProposal,
)


class MemoryRepository:
    """保存版本化权威记录；索引表只保存可重建投影。"""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memory_items (
                    memory_id TEXT PRIMARY KEY,
                    memory_type TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    student_id TEXT,
                    session_id TEXT,
                    status TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    item_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_versions (
                    revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    memory_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    item_json TEXT NOT NULL,
                    change_source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(memory_id, version)
                );
                CREATE TABLE IF NOT EXISTS memory_index (
                    memory_id TEXT PRIMARY KEY,
                    version INTEGER NOT NULL,
                    embedding_model TEXT,
                    projection_json TEXT NOT NULL,
                    FOREIGN KEY(memory_id) REFERENCES memory_items(memory_id)
                );
                CREATE TABLE IF NOT EXISTS memory_proposals (
                    proposal_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    proposal_json TEXT NOT NULL,
                    review_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    memory_id TEXT,
                    proposal_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def get(self, memory_id: str) -> MemoryItem | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT item_json FROM memory_items WHERE memory_id = ?", (memory_id,)
            ).fetchone()
        return MemoryItem.model_validate_json(row[0]) if row else None

    def list_items(
        self, *, statuses: Iterable[MemoryStatus | str] | None = None
    ) -> list[MemoryItem]:
        status_values = [
            value.value if isinstance(value, MemoryStatus) else value
            for value in (statuses or [])
        ]
        with closing(self._connect()) as connection:
            if status_values:
                placeholders = ",".join("?" for _ in status_values)
                rows = connection.execute(
                    f"SELECT item_json FROM memory_items WHERE status IN ({placeholders})",
                    status_values,
                ).fetchall()
            else:
                rows = connection.execute("SELECT item_json FROM memory_items").fetchall()
        return [MemoryItem.model_validate_json(row[0]) for row in rows]

    def save(
        self,
        item: MemoryItem,
        *,
        change_source: str = "manual",
        expected_version: int | None = None,
    ) -> MemoryItem:
        # model_copy(update=...) 不会自动重跑 Pydantic 校验；持久化边界必须复验。
        item = MemoryItem.model_validate(item.model_dump(mode="python"))
        payload = item.model_dump_json()
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT version FROM memory_items WHERE memory_id = ?",
                    (item.memory_id,),
                ).fetchone()
                if expected_version is not None and (
                    row is None or int(row[0]) != expected_version
                ):
                    raise ValueError("Memory version conflict.")
                if row is not None and item.version <= int(row[0]):
                    raise ValueError("A memory update must increase version.")
                connection.execute(
                    """
                    INSERT INTO memory_items(
                        memory_id, memory_type, subject, scope, student_id,
                        session_id, status, version, item_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(memory_id) DO UPDATE SET
                        memory_type=excluded.memory_type, subject=excluded.subject,
                        scope=excluded.scope, student_id=excluded.student_id,
                        session_id=excluded.session_id, status=excluded.status,
                        version=excluded.version, item_json=excluded.item_json,
                        updated_at=excluded.updated_at
                    """,
                    (
                        item.memory_id,
                        item.memory_type.value,
                        item.subject,
                        item.scope.value,
                        item.student_id,
                        item.session_id,
                        item.status.value,
                        item.version,
                        payload,
                        now,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO memory_versions(
                        memory_id, version, item_json, change_source, created_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (item.memory_id, item.version, payload, change_source, now),
                )
                if item.status == MemoryStatus.ACTIVE:
                    self._write_index(connection, item)
                else:
                    connection.execute(
                        "DELETE FROM memory_index WHERE memory_id = ?", (item.memory_id,)
                    )
                connection.execute(
                    "INSERT INTO memory_events(event_type, memory_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                    ("memory_saved", item.memory_id, json.dumps({"version": item.version}), now),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return item

    @staticmethod
    def _write_index(connection: sqlite3.Connection, item: MemoryItem) -> None:
        projection = json.dumps(
            {
                "retrieval_text": item.retrieval_text,
                "concept_ids": item.concept_ids,
                "lesson_plan_step_ids": item.lesson_plan_step_ids,
            },
            ensure_ascii=False,
        )
        connection.execute(
            """
            INSERT INTO memory_index(memory_id, version, embedding_model, projection_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(memory_id) DO UPDATE SET version=excluded.version,
                embedding_model=excluded.embedding_model,
                projection_json=excluded.projection_json
            """,
            (item.memory_id, item.version, item.embedding_model, projection),
        )

    def rebuild_index(self) -> int:
        active = self.list_items(statuses=[MemoryStatus.ACTIVE])
        with closing(self._connect()) as connection, connection:
            connection.execute("DELETE FROM memory_index")
            for item in active:
                self._write_index(connection, item)
        return len(active)

    def indexed_ids(self) -> set[str]:
        with closing(self._connect()) as connection:
            rows = connection.execute("SELECT memory_id FROM memory_index").fetchall()
        return {row[0] for row in rows}

    def get_version(self, memory_id: str, version: int) -> MemoryItem | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT item_json FROM memory_versions WHERE memory_id=? AND version=?",
                (memory_id, version),
            ).fetchone()
        return MemoryItem.model_validate_json(row[0]) if row else None

    def rollback(self, memory_id: str, version: int) -> MemoryItem:
        current = self.get(memory_id)
        historical = self.get_version(memory_id, version)
        if current is None or historical is None:
            raise ValueError("Unknown memory version.")
        restored = historical.model_copy(
            update={
                "version": current.version + 1,
                "updated_at": datetime.now(timezone.utc),
                "status": MemoryStatus.ACTIVE,
            }
        )
        return self.save(
            restored, change_source=f"rollback:{version}", expected_version=current.version
        )

    def save_proposal(
        self, proposal: MemoryUpdateProposal, reviews: dict[str, object] | None = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO memory_proposals(
                    proposal_id, status, proposal_json, review_json, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(proposal_id) DO UPDATE SET status=excluded.status,
                    proposal_json=excluded.proposal_json,
                    review_json=excluded.review_json, updated_at=excluded.updated_at
                """,
                (
                    proposal.proposal_id,
                    proposal.status,
                    proposal.model_dump_json(),
                    json.dumps(reviews or {}, ensure_ascii=False),
                    now,
                ),
            )

    def get_proposal(
        self, proposal_id: str
    ) -> tuple[MemoryUpdateProposal, dict[str, object]] | None:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT proposal_json, review_json FROM memory_proposals WHERE proposal_id=?",
                (proposal_id,),
            ).fetchone()
        if row is None:
            return None
        return MemoryUpdateProposal.model_validate_json(row[0]), json.loads(row[1])

    def list_events(self, *, limit: int = 100) -> list[dict[str, object]]:
        bounded_limit = min(max(limit, 1), 1_000)
        with closing(self._connect()) as connection:
            rows = connection.execute(
                """
                SELECT event_id, event_type, memory_id, proposal_id,
                       payload_json, created_at
                FROM memory_events ORDER BY event_id DESC LIMIT ?
                """,
                (bounded_limit,),
            ).fetchall()
        return [
            {
                "event_id": row[0],
                "event_type": row[1],
                "memory_id": row[2],
                "proposal_id": row[3],
                "payload": json.loads(row[4]),
                "created_at": row[5],
            }
            for row in rows
        ]

    def record_event(
        self,
        event_type: str,
        payload: dict[str, object],
        *,
        memory_id: str | None = None,
        proposal_id: str | None = None,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO memory_events(
                    event_type, memory_id, proposal_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_type,
                    memory_id,
                    proposal_id,
                    json.dumps(payload, ensure_ascii=False),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
