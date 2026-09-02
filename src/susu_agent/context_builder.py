"""为 Agent 组装有限、可控的工作上下文。"""

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping, Sequence

from susu_agent.lesson_plan_loader import (
    LessonPlanBundle,
    LessonPlanLoader,
    load_lesson_plan,
)
from susu_agent.schemas.teaching_state import validate_teaching_state


@dataclass(frozen=True, slots=True)
class ContextMessage:
    """传入 ContextBuilder 的一条已筛选原始消息。"""

    role: Literal["user", "assistant"]
    content: str
    message_id: int | None = None

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("Context message content cannot be empty.")


class ContextBuilder:
    """从完整教学状态和有限消息窗口创建 Agent 工作上下文。"""

    def __init__(
        self,
        recent_message_limit: int = 6,
        recent_question_limit: int = 5,
        subject: str | None = None,
        lesson_plan_loader: LessonPlanLoader | None = None,
    ) -> None:
        if recent_message_limit < 1:
            raise ValueError("recent_message_limit must be at least 1.")
        if recent_question_limit < 0:
            raise ValueError("recent_question_limit cannot be negative.")

        self._recent_message_limit = recent_message_limit
        self._recent_question_limit = recent_question_limit
        self._subject_override = subject
        self._lesson_plan_loader = lesson_plan_loader

    def build_payload(
        self,
        teaching_state: Mapping[str, Any],
        recent_messages: Sequence[ContextMessage],
        current_user_message: str,
    ) -> dict[str, Any]:
        """构造可序列化的内部上下文字典。

        recent_messages 应只传入尚未被压缩的历史消息，且不包含
        current_user_message。
        """
        if not current_user_message.strip():
            raise ValueError("current_user_message cannot be empty.")

        state = dict(teaching_state)
        validate_teaching_state(state)

        question_history = state["open_question_history"]
        active_questions = [
            question
            for question in question_history
            if question["status"] == "open"
        ]
        resolved_questions = [
            question
            for question in question_history
            if question["status"] != "open"
        ]

        return {
            "lesson_plan": state["lesson_plan"],
            "original_problem": self._build_problem_context(state),
            "teaching_progress": state.get("teaching_progress", {}),
            "student_session_status": state.get("student_model", {}).get(
                "status", {}
            ),
            "rolling_summary": state["memory_meta"]["rolling_summary"],
            "active_questions": active_questions,
            "recent_question_history": resolved_questions[
                -self._recent_question_limit :
            ]
            if self._recent_question_limit
            else [],
            "recent_messages": [
                asdict(message)
                for message in recent_messages[-self._recent_message_limit :]
            ],
            "current_user_message": current_user_message,
        }

    def build_prompt(
        self,
        teaching_state: Mapping[str, Any],
        recent_messages: Sequence[ContextMessage],
        current_user_message: str,
        lesson_plan: LessonPlanBundle | None = None,
    ) -> str:
        """将工作上下文序列化为可作为 Agent 输入的提示文本。"""
        state_lesson_plan = teaching_state.get("lesson_plan")
        if not isinstance(state_lesson_plan, Mapping):
            raise ValueError("teaching_state must contain lesson_plan metadata.")
        state_subject = state_lesson_plan.get("subject")
        if not isinstance(state_subject, str):
            raise ValueError("teaching_state lesson_plan.subject must be a string.")
        if (
            self._subject_override is not None
            and self._subject_override != state_subject
        ):
            raise ValueError(
                "ContextBuilder subject does not match teaching_state lesson plan."
            )
        subject = self._subject_override or state_subject

        selected_lesson_plan = lesson_plan or (
            self._lesson_plan_loader.load(subject)
            if self._lesson_plan_loader is not None
            else load_lesson_plan(subject)
        )
        if selected_lesson_plan.subject != subject:
            raise ValueError("Lesson plan subject does not match teaching_state.")
        if (
            selected_lesson_plan.content_digest
            != state_lesson_plan.get("content_digest")
        ):
            raise ValueError("Lesson plan snapshot does not match teaching_state.")

        teaching_progress = teaching_state.get("teaching_progress", {})
        current_step_id = (
            teaching_progress.get("current_lesson_plan_step_id")
            if isinstance(teaching_progress, Mapping)
            else None
        )
        context_selection = selected_lesson_plan.select_context(current_step_id)
        payload = self.build_payload(
            teaching_state=teaching_state,
            recent_messages=recent_messages,
            current_user_message=current_user_message,
        )
        context_json = json.dumps(payload, ensure_ascii=False, indent=2)

        return (
            "以下教案资料和教学状态仅供你内部决策使用。"
            "请遵循 instruction 中的教学规则，结合教案选择当前步骤；"
            "不要向学生泄露内部摘要、状态字段或参考答案。\n"
            f"<lesson_plan_context subject=\"{selected_lesson_plan.subject}\" "
            f"version=\"{selected_lesson_plan.lesson_plan_version}\" "
            f"step_id=\"{context_selection.step_id}\" "
            f"sources=\"{' | '.join(context_selection.sources)}\">\n"
            f"{context_selection.content}\n"
            "</lesson_plan_context>\n"
            "<teaching_context>\n"
            f"{context_json}\n"
            "</teaching_context>"
        )

    @staticmethod
    def _build_problem_context(teaching_state: Mapping[str, Any]) -> dict[str, Any]:
        """复制题目信息，并确保标准答案不会进入学生对话上下文。"""
        original_problem = dict(teaching_state.get("original_problem", {}))
        original_problem.pop("reference_answer", None)
        return original_problem
