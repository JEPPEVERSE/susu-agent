import asyncio

from agents import Runner
from dotenv import load_dotenv
from openai.types.responses import ResponseTextDeltaEvent

from logging_config import configure_logging
from susu_agent.choice import Choice, ChoiceAction
from susu_agent.math_tutor import math_tutor_agent
from susu_agent.session import SessionInfo, SessionManager

load_dotenv()

logger = configure_logging()


def print_session_info(session_info: SessionInfo) -> None:
    """展示一条历史会话记录"""
    print(
        f"Session ID: {session_info.session_id}, "
        f"Created At: {session_info.created_at}, "
        f"Updated At: {session_info.updated_at}"
    )


def read_choice() -> Choice:
    while True:
        try:
            raw_value = input("Math question (/new, /exit): ")
        except (EOFError, KeyboardInterrupt):
            logger.info("Received terminal exit signal")
            print()
            return Choice(action=ChoiceAction.EXIT)

        try:
            return Choice.from_raw(raw_value)
        except ValueError as error:
            logger.warning("Rejected an empty user input")
            print(error)


async def stream_answer(question: str, session_manager: SessionManager) -> None:
    try:
        logger.info("Starting an agent response")
        result = Runner.run_streamed(
            math_tutor_agent,
            input=question,
            session=session_manager.current_session,
        )

        async for event in result.stream_events():
            if (
                event.type == "raw_response_event"
                and isinstance(event.data, ResponseTextDeltaEvent)
            ):
                print(
                    event.data.delta,
                    end="",
                    flush=True,
                )
    except Exception as error:
        logger.exception("Agent request failed")
        print(
            f"Request failed ({type(error).__name__}): {error}",
            end="",
        )
    finally:
        print()


async def main() -> None:
    logger.info("Starting Math Tutor Agent")
    print("欢迎使用速速提分 Agent!")
    print("请输入一个数学问题.")
    print("1. 输入 /new 来开启新对话.")
    print("2. 输入 /history 来查看历史对话.")
    print("3. 输入 /exit 来退出程序.")

    session_manager = SessionManager()
    session_manager.start_new_session()

    try:
        while True:
            choice = read_choice()

            if choice.action is ChoiceAction.EXIT:
                logger.info("User exited the application")
                break

            if choice.action is ChoiceAction.NEW_CHAT:
                logger.info("Starting a new chat session")
                session_manager.start_new_session()
                print(f"Started a new chat: {session_manager.current_session_id}")
                continue

            if choice.action is ChoiceAction.HISTORY:
                logger.info("User requested chat history")

                sessions = session_manager.list_sessions()
                if not sessions:
                    print("暂无历史会话.")
                    continue

                for session_info in sessions:
                    print_session_info(session_info)

                new_session_id = input("请输入想要切换的会话 ID: ")
                try:
                    session_manager.switch_to_session(new_session_id)
                    print(f"Switched to session: {session_manager.current_session_id}")
                except ValueError:
                    logger.warning("Invalid session ID entered: %s", new_session_id)
                    print("无效的会话ID，请重试.")
                continue

            await stream_answer(choice.question, session_manager)
    finally:
        session_manager.close()

    print("感谢使用！")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n感谢使用！")
