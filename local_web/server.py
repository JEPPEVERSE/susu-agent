"""susu-agent v0.2 的本地轻量测试页面。"""

import argparse
import asyncio
import json
import os
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIRECTORY = PROJECT_ROOT / "src"
STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"
if str(SRC_DIRECTORY) not in sys.path:
    sys.path.insert(0, str(SRC_DIRECTORY))

from dotenv import load_dotenv  # noqa: E402

from susu_agent.context_builder import ContextMessage  # noqa: E402
from susu_agent.orchestrator import V02Orchestrator  # noqa: E402
from susu_agent.repositories.student_model_repository import (  # noqa: E402
    StudentModelRepository,
)
from susu_agent.repositories.teaching_state_repository import (  # noqa: E402
    TeachingStateRepository,
)
from susu_agent.session import SessionManager  # noqa: E402


load_dotenv(PROJECT_ROOT / ".env")


class TutorWebRuntime:
    """串行管理单用户页面所需的 Session 和 Tutor 调用。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._session_manager = SessionManager()
        subject = os.getenv("COURSE_SUBJECT", "math").strip() or "math"
        self._state_repository = TeachingStateRepository(
            self._session_manager.db_path,
            default_subject=subject,
        )
        self._student_repository = StudentModelRepository(
            self._session_manager.db_path
        )
        self._student_id = os.getenv("STUDENT_ID", "default_student")
        self._orchestrator = V02Orchestrator(
            self._state_repository,
            self._student_repository,
            student_id=self._student_id,
            grade=os.getenv("COURSE_GRADE", "unknown"),
        )
        self._start_new_session()

    def close(self) -> None:
        with self._lock:
            self._session_manager.close()

    def bootstrap(self) -> dict[str, Any]:
        with self._lock:
            return self._bootstrap_unlocked()

    def ask(self, question: str) -> dict[str, Any]:
        normalized_question = question.strip()
        if not normalized_question:
            raise ValueError("问题不能为空。")
        if len(normalized_question) > 8_000:
            raise ValueError("问题过长，请控制在 8000 个字符以内。")

        with self._lock:
            teacher_response = asyncio.run(
                self._ask_async(normalized_question)
            )
            return {
                "answer": teacher_response,
                **self._bootstrap_unlocked(include_messages=False),
            }

    def new_session(self) -> dict[str, Any]:
        with self._lock:
            self._start_new_session()
            return self._bootstrap_unlocked()

    def switch_session(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            self._session_manager.switch_to_session(session_id)
            self._state_repository.get_or_create(session_id)
            return self._bootstrap_unlocked()

    async def _ask_async(self, question: str) -> str:
        items = await self._session_manager.current_session.get_items(limit=4)
        recent_messages = [
            message
            for item in items
            if (message := _to_context_message(item)) is not None
        ]
        teacher_response, _ = await self._orchestrator.run_turn(
            self._require_session_id(),
            question,
            recent_messages,
        )
        await self._session_manager.current_session.add_items(
            [
                {"role": "user", "content": question},
                {"role": "assistant", "content": teacher_response},
            ]
        )
        await self._orchestrator.summarize_if_needed(
            self._require_session_id()
        )
        return teacher_response

    def _start_new_session(self) -> None:
        self._session_manager.start_new_session()
        session_id = self._require_session_id()
        self._state_repository.get_or_create(session_id)

    def _bootstrap_unlocked(
        self,
        *,
        include_messages: bool = True,
    ) -> dict[str, Any]:
        session_id = self._require_session_id()
        state = self._state_repository.get_or_create(session_id)
        sessions = [
            {
                "session_id": item.session_id,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
            }
            for item in self._session_manager.list_sessions()
        ]
        payload: dict[str, Any] = {
            "session_id": session_id,
            "teaching_state": state,
            "student_model": self._student_repository.get_or_create(
                self._student_id,
                os.getenv("COURSE_GRADE", "unknown"),
            ),
            "v02_runtime": {
                "architecture_version": "0.2",
                "solution_ready": state.get("solution") is not None,
                "verification_ready": state.get("verification_report") is not None,
                "strategy_ready": state.get("teaching_strategy") is not None,
                "solution_revision": state.get("v02_meta", {}).get(
                    "solution_revision", 0
                ),
                "summary_completed": state.get("v02_meta", {}).get(
                    "summary_completed", False
                ),
            },
            "sessions": sessions,
        }
        if include_messages:
            payload["messages"] = asyncio.run(self._read_messages())
        return payload

    async def _read_messages(self) -> list[dict[str, str]]:
        items = await self._session_manager.current_session.get_items(limit=50)
        messages: list[dict[str, str]] = []
        for item in items:
            message = _to_message(item)
            if message is not None:
                messages.append(message)
        return messages

    def _require_session_id(self) -> str:
        session_id = self._session_manager.current_session_id
        if session_id is None:
            raise RuntimeError("当前没有可用会话。")
        return session_id


def _to_message(item: object) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    role = item.get("role")
    if role not in {"user", "assistant"}:
        return None
    content = item.get("content")
    if isinstance(content, str):
        text = content.strip()
    elif isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                value = block.get("text") or block.get("content")
                if isinstance(value, str):
                    parts.append(value)
        text = "\n".join(parts).strip()
    else:
        return None
    if not text:
        return None
    return {"role": role, "content": text}


def _to_context_message(item: object) -> ContextMessage | None:
    message = _to_message(item)
    if message is None:
        return None
    return ContextMessage(role=message["role"], content=message["content"])


class TutorRequestHandler(BaseHTTPRequestHandler):
    runtime: TutorWebRuntime

    _STATIC_ROUTES = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    }

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/bootstrap":
            self._handle_json_action(self.runtime.bootstrap)
            return
        static_route = self._STATIC_ROUTES.get(path)
        if static_route is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        filename, content_type = static_route
        content = (STATIC_DIRECTORY / filename).read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            body = self._read_json_body()
        except (ValueError, json.JSONDecodeError) as error:
            self._send_json(
                {"error": str(error)},
                status=HTTPStatus.BAD_REQUEST,
            )
            return

        if path == "/api/chat":
            self._handle_json_action(
                lambda: self.runtime.ask(str(body.get("question", "")))
            )
        elif path == "/api/sessions/new":
            self._handle_json_action(self.runtime.new_session)
        elif path == "/api/sessions/switch":
            self._handle_json_action(
                lambda: self.runtime.switch_session(
                    str(body.get("session_id", ""))
                )
            )
        else:
            self._send_json(
                {"error": "接口不存在。"},
                status=HTTPStatus.NOT_FOUND,
            )

    def log_message(self, format: str, *args: object) -> None:
        print(f"[web] {self.address_string()} - {format % args}")

    def _read_json_body(self) -> dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", "0"))
        if content_length <= 0 or content_length > 1_000_000:
            raise ValueError("请求正文大小无效。")
        body = json.loads(self.rfile.read(content_length).decode("utf-8"))
        if not isinstance(body, dict):
            raise ValueError("请求正文必须是 JSON 对象。")
        return body

    def _handle_json_action(self, action: Any) -> None:
        try:
            self._send_json(action())
        except ValueError as error:
            self._send_json(
                {"error": str(error)},
                status=HTTPStatus.BAD_REQUEST,
            )
        except Exception as error:
            self._send_json(
                {"error": f"{type(error).__name__}: {error}"},
                status=HTTPStatus.INTERNAL_SERVER_ERROR,
            )

    def _send_json(
        self,
        payload: dict[str, Any],
        *,
        status: HTTPStatus = HTTPStatus.OK,
    ) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 susuAgent v0.2 测试页面。")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    runtime = TutorWebRuntime()
    TutorRequestHandler.runtime = runtime
    server = ThreadingHTTPServer((args.host, args.port), TutorRequestHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"susuAgent v0.2 测试页面已启动：{url}")
    print("按 Ctrl+C 停止服务。")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务……")
    finally:
        server.server_close()
        runtime.close()


if __name__ == "__main__":
    main()
