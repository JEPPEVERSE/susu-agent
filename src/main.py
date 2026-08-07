import asyncio

from agents import Runner, SQLiteSession
from dotenv import load_dotenv
from openai.types.responses import ResponseTextDeltaEvent

from logging_config import configure_logging
from susu_agent.choice import Choice, ChoiceAction
from susu_agent.math_tutor import math_tutor_agent

load_dotenv()

SESSION_PREFIX = "problem"
logger = configure_logging()


def create_session(session_number: int) -> SQLiteSession:
    session_id = f"{SESSION_PREFIX}_{session_number}"
    logger.info("Creating session %s", session_id)
    return SQLiteSession(session_id)


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


async def stream_answer(question: str, session: SQLiteSession) -> None:
    try:
        logger.info("Starting an agent response")
        result = Runner.run_streamed(
            math_tutor_agent,
            input=question,
            session=session,
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
    print("Welcome to the Math Tutor Agent!")
    print("Enter a math question to talk with the tutor.")
    print("Enter /new to start a new chat.")
    print("Enter /exit to exit.")

    session_number = 0
    session = create_session(session_number)

    try:
        while True:
            choice = read_choice()

            if choice.action is ChoiceAction.EXIT:
                logger.info("User exited the application")
                break

            if choice.action is ChoiceAction.NEW_CHAT:
                logger.info("Starting a new chat session")
                session.close()
                session_number += 1
                session = create_session(session_number)
                print(f"Started a new chat: {SESSION_PREFIX}_{session_number}")
                continue

            await stream_answer(choice.question, session)
    finally:
        session.close()
        logger.info("Closed active session")

    print("Thanks for using. See you next time!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nThanks for using. See you next time!")
