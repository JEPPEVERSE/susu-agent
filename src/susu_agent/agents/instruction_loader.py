"""加载与 Agent 实现分离存放的 Markdown instruction。"""

from pathlib import Path


INSTRUCTIONS_DIRECTORY = Path(__file__).resolve().parent.parent / "instructions"


def load_instruction(filename: str) -> str:
    """读取一个 instruction 文件，并在文件缺失时给出明确错误。"""
    instruction_path = INSTRUCTIONS_DIRECTORY / filename
    if not instruction_path.is_file():
        raise FileNotFoundError(
            f"Instruction file does not exist: {instruction_path}"
        )
    return instruction_path.read_text(encoding="utf-8")
