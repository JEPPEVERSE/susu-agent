import asyncio

from agents import Agent, Runner

agent = Agent(
    name = "MyAgent", 
    instructions = "answer the following question"
)

async def main():
    result = await Runner.run(agent, "When did the Roman Empire fall?")
    print(result.final_output)

asyncio.run(main())