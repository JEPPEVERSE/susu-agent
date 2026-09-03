from dataclasses import dataclass

from agents import Agent, RunContextWrapper

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.model_config import resolve_agent_model


@dataclass(frozen=True, slots=True)
class TutorRunContext:
    """持有本次 Tutor 运行共享的不可变教案快照。"""

    lesson_plan: LessonPlanBundle


def compose_tutor_instructions(lesson_plan: LessonPlanBundle) -> str:
    """组合跨学科总规则与指定学科的动态教案 instruction。"""
    general_instruction = load_instruction("tutor_instruction.md").strip()
    step_catalog = "\n".join(
        f"- {step.step_id}: {step.name}" for step in lesson_plan.steps
    )
    return (
        f"{general_instruction}\n\n"
        f"<lesson_plan_instruction subject=\"{lesson_plan.subject}\" "
        f"version=\"{lesson_plan.lesson_plan_version}\" "
        f"sources=\"{' | '.join(lesson_plan.instruction_sources)}\">\n"
        "## 结构化步骤目录\n\n"
        f"{step_catalog}\n\n"
        f"{lesson_plan.instruction}\n"
        "</lesson_plan_instruction>"
    )


def provide_tutor_instructions(
    context: RunContextWrapper[TutorRunContext],
    _agent: Agent[TutorRunContext],
) -> str:
    """根据本次运行的 subject 动态选择并加载教案。"""
    return compose_tutor_instructions(context.context.lesson_plan)


tutor_agent = Agent[TutorRunContext](
    name="tutor",
    instructions=provide_tutor_instructions,
    model=resolve_agent_model("TUTOR_MODEL"),
)
