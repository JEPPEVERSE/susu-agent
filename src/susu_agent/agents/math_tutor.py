from agents import Agent

from susu_agent.agents.instruction_loader import load_instruction


math_tutor_agent = Agent(
    name="math_tutor",
    instructions=load_instruction("math_tutor_instruction.md"),
)
