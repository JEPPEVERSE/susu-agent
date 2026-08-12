from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from agents import Agent
from pydantic import BaseModel, Field

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.schemas.teaching_state import validate_teaching_state


class TeachingStateUpdate(BaseModel):
    """状态更新 Agent 对单轮对话产生的增量更新。"""

    stage: Literal[
        "understand_problem",
        "recall_knowledge",
        "make_plan",
        "solve",
        "verify",
        "complete",
    ] | None = None

    confirmed_steps_to_add: list[str] = Field(default_factory=list)
    misconceptions_to_add: list[str] = Field(default_factory=list)

    open_question: str | None = None
    next_teacher_action: Literal[
        "ask_question",
        "give_hint",
        "explain",
        "verify_answer",
    ] | None = None

    rolling_summary: str | None = None


teaching_state_updater = Agent(
    name="teaching_state_updater",
    instructions=load_instruction("teaching_state_updater_instruction.md"),
    output_type=TeachingStateUpdate,
)


def apply_teaching_state_update(
    current_teaching_state: Mapping[str, Any],
    update: TeachingStateUpdate,
) -> dict[str, Any]:
    """将状态更新 Agent 的增量结果合并到完整教学状态。"""
    next_state = deepcopy(dict(current_teaching_state))
    now = datetime.now(timezone.utc).isoformat()
    teaching_progress = next_state.setdefault("teaching_progress", {})
    student_status = next_state.setdefault("student_model", {}).setdefault(
        "status", {}
    )

    if update.stage is not None:
        teaching_progress["stage"] = update.stage
    if update.next_teacher_action is not None:
        teaching_progress["next_teacher_action"] = update.next_teacher_action

    _extend_unique(
        teaching_progress.setdefault("confirmed_steps", []),
        update.confirmed_steps_to_add,
        maximum_size=20,
    )
    _extend_unique(
        student_status.setdefault("main_misconceptions", []),
        update.misconceptions_to_add,
        maximum_size=10,
    )

    if update.open_question is not None:
        teaching_progress["open_question"] = update.open_question
        _replace_open_question(
            next_state.setdefault("open_question_history", []),
            question=update.open_question,
            stage=teaching_progress.get("stage", "understand_problem"),
            now=now,
        )

    if update.rolling_summary is not None:
        next_state["memory_meta"]["rolling_summary"] = update.rolling_summary

    next_state["updated_at"] = now
    validate_teaching_state(next_state)
    return next_state


def _extend_unique(
    existing_items: list[str],
    new_items: list[str],
    *,
    maximum_size: int,
) -> None:
    """去重追加列表项，同时遵守教学状态 Schema 的容量上限。"""
    for item in new_items:
        if item not in existing_items and len(existing_items) < maximum_size:
            existing_items.append(item)


def _replace_open_question(
    question_history: list[dict[str, Any]],
    *,
    question: str,
    stage: str,
    now: str,
) -> None:
    """关闭先前未答问题，并将本轮新问题写入历史。"""
    if any(
        item["status"] == "open" and item["question"] == question
        for item in question_history
    ):
        return

    for item in question_history:
        if item["status"] == "open":
            item["status"] = "superseded"
            item["resolved_at"] = now

    next_question_number = max(
        (
            int(item["question_id"].removeprefix("question_"))
            for item in question_history
        ),
        default=-1,
    ) + 1
    question_history.append(
        {
            "question_id": f"question_{next_question_number}",
            "question": question,
            "stage": stage,
            "status": "open",
            "asked_at": now,
            "student_answer_summary": None,
            "agent_assessment": {
                "understanding": "not_answered",
                "summary": "",
            },
            "resolved_at": None,
        }
    )
