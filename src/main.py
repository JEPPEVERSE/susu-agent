import asyncio

from agents import Runner
from dotenv import load_dotenv
from openai.types.responses import ResponseTextDeltaEvent

from susu_agent.math_tutor import math_tutor_agent

load_dotenv()


async def get_answer(question: str) -> None:
    result = Runner.run_streamed(
        math_tutor_agent,
        input=question,
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

    print()


async def main() -> None:
    while True:
        question = input("请输入你的数学问题（输入 'exit' 退出）：")
        if question.lower() == "exit":
            break

        await get_answer(question)


if __name__ == "__main__":
    asyncio.run(main())
