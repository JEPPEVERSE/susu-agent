import asyncio
import json
import os
from dataclasses import dataclass

from agents import Runner
from dotenv import load_dotenv
from openai.types.responses import ResponseTextDeltaEvent

from logging_config import configure_logging
from susu_agent.agents.tutor import TutorRunContext, tutor_agent
from susu_agent.agents.teaching_state_updater import (
    TeachingStateUpdate,
    apply_teaching_state_update,
    teaching_state_updater,
)
from susu_agent.choice import Choice, ChoiceAction
from susu_agent.context_builder import ContextBuilder, ContextMessage
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.repositories.teaching_state_repository import TeachingStateRepository
from susu_agent.session import SessionInfo, SessionManager

load_dotenv()

logger = configure_logging()
course_subject = os.getenv("COURSE_SUBJECT", "math").strip() or "math"
context_builder = ContextBuilder(recent_message_limit=6)


@dataclass(frozen=True, slots=True)
class TutorTurn:
    """同一轮教学共享的输入、状态和教案快照。"""

    context_input: str
    teaching_state: dict[str, object]
    lesson_plan: LessonPlanBundle


def print_session_info(session_info: SessionInfo) -> None:
    """展示一条历史会话记录。"""
    print(
        f"Session ID: {session_info.session_id}, "
        f"Created At: {session_info.created_at}, "
        f"Updated At: {session_info.updated_at}"
    )


def print_current_runtime_state(
    session_manager: SessionManager,
    teaching_state_repository: TeachingStateRepository,
) -> None:
    """以 JSON 展示当前会话及其教学状态，方便本地调试。"""
    session_id = session_manager.current_session_id
    if session_id is None:
        print("当前没有活跃会话。")
        return

    current_teaching_state = teaching_state_repository.get_or_create(session_id)
    print("\n--- Current Runtime State ---")
    print(f"session_id: {session_id}")
    print("current_teaching_state:")
    print(json.dumps(current_teaching_state, ensure_ascii=False, indent=2))
    print("-----------------------------\n")


def start_and_show_session(
    session_manager: SessionManager,
    teaching_state_repository: TeachingStateRepository,
) -> None:
    """创建一个新会话，并初始化、展示它对应的教学状态。"""
    session_manager.start_new_session()
    print_current_runtime_state(session_manager, teaching_state_repository)


def show_history_and_switch_session(
    session_manager: SessionManager,
    teaching_state_repository: TeachingStateRepository,
) -> None:
    """展示可恢复的会话，并按用户输入完成切换。"""
    logger.info("User requested chat history")
    sessions = session_manager.list_sessions()
    if not sessions:
        print("暂无历史会话。")
        return

    for session_info in sessions:
        print_session_info(session_info)

    try:
        new_session_id = input("请输入想要切换的会话 ID：").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        return

    try:
        session_manager.switch_to_session(new_session_id)
    except ValueError:
        logger.warning("Invalid session ID entered: %s", new_session_id)
        print("无效的会话 ID，请重试。")
        return

    print_current_runtime_state(session_manager, teaching_state_repository)


def read_choice() -> Choice:
    while True:
        try:
            raw_value = input("学习问题（/new、/history、/status、/exit）：")
        except (EOFError, KeyboardInterrupt):
            logger.info("Received terminal exit signal")
            print()
            return Choice(action=ChoiceAction.EXIT)

        try:
            return Choice.from_raw(raw_value)
        except ValueError as error:
            logger.warning("Rejected an empty user input")
            print(error)


async def build_tutor_input(
    question: str,
    session_manager: SessionManager,
    teaching_state_repository: TeachingStateRepository,
) -> TutorTurn:
    """从存档中读取有限消息，并用 ContextBuilder 组装本轮模型输入。"""
    session_id = session_manager.current_session_id
    if session_id is None:
        raise RuntimeError("Cannot build context without an active session.")

    teaching_state, lesson_plan = (
        teaching_state_repository.get_or_create_with_lesson_plan(session_id)
    )
    if "original_problem" not in teaching_state:
        teaching_state["original_problem"] = {"problem_statement": question}

    stored_items = await session_manager.current_session.get_items(limit=6)
    recent_messages = [
        context_message
        for item in stored_items
        if (context_message := to_context_message(item)) is not None
    ]
    tutor_turn = TutorTurn(
        context_input=context_builder.build_prompt(
            teaching_state=teaching_state,
            recent_messages=recent_messages,
            current_user_message=question,
            lesson_plan=lesson_plan,
        ),
        teaching_state=teaching_state,
        lesson_plan=lesson_plan,
    )
    logger.debug(
        "Built tutor context for session %s using %d archived messages",
        session_id,
        len(recent_messages),
    )
    return tutor_turn


def to_context_message(item: object) -> ContextMessage | None:
    """将 SQLiteSession 的消息格式转换为 ContextBuilder 所需的简洁格式。"""
    if not isinstance(item, dict):
        return None

    role = item.get("role")
    if role not in {"user", "assistant"}:
        return None

    content = extract_text_content(item.get("content"))
    if not content:
        return None

    return ContextMessage(role=role, content=content)


def extract_text_content(content: object) -> str:
    """兼容 SDK 消息中字符串或内容块列表两种 content 结构。"""
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""

    text_parts: list[str] = []
    for block in content:
        if not isinstance(block, dict):
            continue
        text = block.get("text") or block.get("content")
        if isinstance(text, str):
            text_parts.append(text)
    return "\n".join(text_parts).strip()


async def persist_conversation_turn(
    question: str,
    teacher_response: str,
    session_manager: SessionManager,
) -> None:
    """把原始问答写入 SQLiteSession，仅用于审计和下一轮有限窗口读取。"""
    await session_manager.current_session.add_items(
        [
            {"role": "user", "content": question},
            {"role": "assistant", "content": teacher_response},
        ]
    )
    logger.debug(
        "Persisted conversation turn for session %s",
        session_manager.current_session_id,
    )


async def stream_answer(
    context_input: str,
    lesson_plan: LessonPlanBundle,
) -> str | None:
    try:
        logger.info(
            "Starting tutor agent response for lesson plan %s",
            lesson_plan.subject,
        )
        result = Runner.run_streamed(
            tutor_agent,
            input=context_input,
            context=TutorRunContext(lesson_plan=lesson_plan),
        )

        async for event in result.stream_events():
            if (
                event.type == "raw_response_event"
                and isinstance(event.data, ResponseTextDeltaEvent)
            ):
                print(event.data.delta, end="", flush=True)
        logger.info("Tutor agent response completed")
        return str(result.final_output)
    except Exception as error:
        logger.exception("Agent request failed")
        print(f"Request failed ({type(error).__name__}): {error}", end="")
        return None
    finally:
        print()


async def update_teaching_state(
    question: str,
    teacher_response: str,
    current_teaching_state: dict[str, object],
    lesson_plan: LessonPlanBundle,
    teaching_state_repository: TeachingStateRepository,
) -> None:
    """调用后台更新器，合并并保存本轮教学状态。"""
    session_id = current_teaching_state["session_id"]
    if "original_problem" not in current_teaching_state:
        current_teaching_state["original_problem"] = {
            "problem_statement": question,
        }

    updater_input = json.dumps(
        {
            "current_teaching_state": current_teaching_state,
            "student_message": question,
            "teacher_response": teacher_response,
            "lesson_plan_instruction": lesson_plan.instruction,
            "lesson_plan_steps": [
                {"id": step.step_id, "name": step.name}
                for step in lesson_plan.steps
            ],
        },
        ensure_ascii=False,
    )

    try:
        result = await Runner.run(
            teaching_state_updater,
            input=updater_input,
        )
        update = result.final_output
        if not isinstance(update, TeachingStateUpdate):
            raise TypeError("Teaching state updater returned an unexpected output type.")

        next_teaching_state = apply_teaching_state_update(
            current_teaching_state,
            update,
        )
        teaching_state_repository.save(
            next_teaching_state,
            lesson_plan=lesson_plan,
        )
        logger.info("Updated teaching state for session %s", session_id)
    except Exception:
        logger.exception("Teaching state update failed for session %s", session_id)


async def main() -> None:
    logger.info("Starting Tutor Agent for subject %s", course_subject)
    print("欢迎使用速速提分 Agent！")
    print(f"当前学科：{course_subject}。请输入学习问题。")
    print("/new：开启新对话；/history：查看并切换历史会话。")
    print("/status：查看 session_id 和 current_teaching_state；/exit：退出。")

    session_manager = SessionManager()
    teaching_state_repository = TeachingStateRepository(
        session_manager.db_path,
        default_subject=course_subject,
    )
    start_and_show_session(session_manager, teaching_state_repository)

    try:
        while True:
            choice = read_choice()

            if choice.action is ChoiceAction.EXIT:
                logger.info("User exited the application")
                break

            if choice.action is ChoiceAction.NEW_CHAT:
                logger.info("Starting a new chat session")
                start_and_show_session(session_manager, teaching_state_repository)
                continue

            if choice.action is ChoiceAction.STATUS:
                print_current_runtime_state(session_manager, teaching_state_repository)
                continue

            if choice.action is ChoiceAction.HISTORY:
                show_history_and_switch_session(
                    session_manager,
                    teaching_state_repository,
                )
                continue

            try:
                tutor_turn = await build_tutor_input(
                    choice.question,
                    session_manager,
                    teaching_state_repository,
                )
            except Exception:
                logger.exception("Failed to build tutor context")
                print("无法构建本轮教学上下文，请重试。")
                continue

            teacher_response = await stream_answer(
                tutor_turn.context_input,
                tutor_turn.lesson_plan,
            )
            if teacher_response is not None:
                try:
                    await persist_conversation_turn(
                        choice.question,
                        teacher_response,
                        session_manager,
                    )
                except Exception:
                    logger.exception("Failed to persist conversation turn")
                await update_teaching_state(
                    choice.question,
                    teacher_response,
                    tutor_turn.teaching_state,
                    tutor_turn.lesson_plan,
                    teaching_state_repository,
                )
                print_current_runtime_state(
                    session_manager,
                    teaching_state_repository,
                )
    finally:
        session_manager.close()

    print("感谢使用！")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        print("\n感谢使用！")
    except Exception:
        logger.exception("Application terminated unexpectedly")
        raise
