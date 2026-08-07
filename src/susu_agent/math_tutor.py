from pathlib import Path

from agents import Agent

current_directory = Path(__file__).resolve().parent

instruction_path = (
    current_directory
    / "instructions"
    / "math_tutor_instruction.md"
)

instruction = instruction_path.read_text(encoding="utf-8")

math_tutor_agent = Agent(
    name="math_tutor",
    instructions=instruction,
)
