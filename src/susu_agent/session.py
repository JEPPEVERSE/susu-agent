"""会话的创建、切换、查询与关闭。"""

import logging
import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from agents import SQLiteSession

DEFAULT_SESSION_DB_PATH = Path("data/sessions.db")
DEFAULT_SESSION_PREFIX = "problem"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SessionInfo:
    """历史会话的基本信息。"""

    session_id: str
    created_at: str
    updated_at: str


class SessionManager:
    """管理一个运行中的 SQLiteSession 及其生命周期。"""

    def __init__(
        self,
        db_path: str | Path | None = None,
        session_prefix: str = DEFAULT_SESSION_PREFIX,
    ) -> None:
        configured_path = os.getenv("SESSION_DB_PATH", str(DEFAULT_SESSION_DB_PATH))
        self._db_path = Path(db_path or configured_path)
        self._session_prefix = session_prefix
        self._session: SQLiteSession | None = None
        self._next_session_number = self._find_next_session_number()

    @property
    def current_session(self) -> SQLiteSession:
        """返回当前会话；尚未创建时提示调用方先创建。"""
        if self._session is None:
            raise RuntimeError("No active session. Call start_new_session() first.")
        return self._session

    @property
    def current_session_id(self) -> str | None:
        """返回当前会话 ID；没有活跃会话时返回 None。"""
        if self._session is None:
            return None
        return self._session.session_id

    def start_new_session(self) -> SQLiteSession:
        """关闭旧会话并创建一个新的会话。"""
        self.close()

        session_id = f"{self._session_prefix}_{self._next_session_number}"
        self._next_session_number += 1
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        logger.info("Creating session %s", session_id)
        self._session = SQLiteSession(session_id, str(self._db_path))
        return self._session

    def list_sessions(self) -> list[SessionInfo]:
        """按最近更新时间倒序返回已持久化的会话。"""
        if not self._db_path.exists():
            return []

        try:
            with sqlite3.connect(self._db_path) as connection:
                cursor = connection.execute(
                    """
                    SELECT session_id, created_at, updated_at
                    FROM agent_sessions
                    ORDER BY updated_at DESC
                    """
                )
                return [SessionInfo(*row) for row in cursor.fetchall()]
        except sqlite3.OperationalError as error:
            if "no such table: agent_sessions" in str(error):
                return []
            raise

    def switch_to_session(self, session_id: str) -> SQLiteSession:
        """切换到一个已经持久化的会话。"""
        normalized_session_id = session_id.strip()
        known_session_ids = {session.session_id for session in self.list_sessions()}
        if normalized_session_id not in known_session_ids:
            raise ValueError("Invalid session ID.")

        self.close()
        logger.info("Switching to session %s", normalized_session_id)
        self._session = SQLiteSession(normalized_session_id, str(self._db_path))
        return self._session

    def close(self) -> None:
        """关闭当前会话；重复调用是安全的。"""
        if self._session is None:
            return

        self._session.close()
        self._session = None
        logger.info("Closed active session")

    def _find_next_session_number(self) -> int:
        """从已有 problem_数字 会话中推导下一个可用编号。"""
        pattern = re.compile(rf"^{re.escape(self._session_prefix)}_(\d+)$")
        session_numbers = [
            int(match.group(1))
            for session in self.list_sessions()
            if (match := pattern.match(session.session_id))
        ]
        return max(session_numbers, default=-1) + 1
