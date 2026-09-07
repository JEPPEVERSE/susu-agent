from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from agents import Agent
from pydantic import BaseModel, Field

from susu_agent.agents.instruction_loader import load_instruction
from susu_agent.model_config import (
    resolve_agent_model,
    supports_native_structured_output,
)
from susu_agent.schemas.teaching_state import validate_teaching_state
from susu_agent.schemas.v02 import TeachingExecution
from susu_agent.structured_output import build_json_output_instruction


class TeachingStateUpdate(BaseModel):
    """状态更新 Agent 对单轮对话产生的增量更新。"""

    stage: Literal[
        "understand_task",
        "recall_knowledge",
        "make_plan",
        "execute",
        "verify",
        "complete",
    ] | None = None

    current_strategy_node_id: str | None = Field(default=None, max_length=100)

    current_lesson_plan_step_id: str | None = Field(
        default=None,
        max_length=200,
    )
    completed_lesson_plan_step_ids_to_add: list[str] = Field(
        default_factory=list,
    )
    lesson_plan_step_summary: str | None = Field(
        default=None,
        max_length=1_000,
    )
    current_solution_step_id: str | None = Field(
        default=None,
        max_length=100,
    )
    completed_solution_step_ids_to_add: list[str] = Field(
        default_factory=list,
    )
    solution_step_summary: str | None = Field(
        default=None,
        max_length=1_000,
    )
    current_solution_question_id: str | None = Field(
        default=None,
        max_length=100,
    )
    completed_solution_question_ids_to_add: list[str] = Field(
        default_factory=list,
    )

    confirmed_steps_to_add: list[str] = Field(default_factory=list)
    misconceptions_to_add: list[str] = Field(default_factory=list)

    open_question: str | None = Field(default=None, min_length=1, max_length=1_000)
    answered_open_question_summary: str | None = Field(
        default=None,
        max_length=500,
    )
    answered_open_question_understanding: Literal[
        "no_idea",
        "incorrect",
        "partially_correct",
        "correct",
        "unclear",
    ] | None = None
    answered_open_question_assessment: str | None = Field(
        default=None,
        max_length=500,
    )
    next_teacher_action: Literal[
        "ask_question",
        "give_hint",
        "explain",
        "verify_answer",
    ] | None = None

    rolling_summary: str | None = None


TEACHING_STATE_UPDATER_MODEL = resolve_agent_model(
    "TEACHING_STATE_UPDATER_MODEL"
)
TEACHING_STATE_UPDATER_USES_NATIVE_OUTPUT = (
    supports_native_structured_output(TEACHING_STATE_UPDATER_MODEL)
)
TEACHING_STATE_UPDATER_INSTRUCTIONS = load_instruction(
    "teaching_state_updater_instruction.md"
)
if not TEACHING_STATE_UPDATER_USES_NATIVE_OUTPUT:
    TEACHING_STATE_UPDATER_INSTRUCTIONS += build_json_output_instruction(
        TeachingStateUpdate
    )


teaching_state_updater = Agent(
    name="teaching_state_updater",
    instructions=TEACHING_STATE_UPDATER_INSTRUCTIONS,
    model=TEACHING_STATE_UPDATER_MODEL,
    output_type=(
        TeachingStateUpdate
        if TEACHING_STATE_UPDATER_USES_NATIVE_OUTPUT
        else None
    ),
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

    selected_strategy_node: Mapping[str, Any] | None = None
    if update.current_strategy_node_id is not None:
        strategy = next_state.get("teaching_strategy") or {}
        strategy_nodes = {
            node.get("node_id"): node for node in strategy.get("nodes", [])
        }
        if update.current_strategy_node_id not in strategy_nodes:
            raise ValueError("Unknown teaching strategy node id.")
        selected_strategy_node = strategy_nodes[update.current_strategy_node_id]
        teaching_progress["current_strategy_node_id"] = (
            update.current_strategy_node_id
        )

    if update.stage is not None:
        teaching_progress["stage"] = update.stage
    if update.next_teacher_action is not None:
        teaching_progress["next_teacher_action"] = update.next_teacher_action
    allowed_step_ids = set(next_state["lesson_plan"]["step_ids"])
    if update.current_lesson_plan_step_id is not None:
        _require_known_step_id(
            update.current_lesson_plan_step_id,
            allowed_step_ids,
        )
        teaching_progress["current_lesson_plan_step_id"] = (
            update.current_lesson_plan_step_id
        )
    if update.lesson_plan_step_summary is not None:
        teaching_progress["lesson_plan_step_summary"] = (
            update.lesson_plan_step_summary
        )

    solution_steps = {
        step["solution_step_id"]: step
        for step in (next_state.get("solution") or {}).get("steps", [])
    }
    solution_questions = {
        question["question_id"]: (step, question)
        for step in solution_steps.values()
        for question in step.get("tutor_questions", [])
    }
    if selected_strategy_node is not None:
        strategy_step_id = selected_strategy_node.get("solution_step_id")
        strategy_question_id = selected_strategy_node.get("solution_question_id")
        if (
            strategy_step_id is not None
            and update.current_solution_step_id is not None
            and update.current_solution_step_id != strategy_step_id
        ):
            raise ValueError("Teaching node and Solution step updates are inconsistent.")
        if (
            strategy_question_id is not None
            and update.current_solution_question_id is not None
            and update.current_solution_question_id != strategy_question_id
        ):
            raise ValueError("Teaching node and Solution question updates are inconsistent.")
        teaching_progress["current_solution_step_id"] = strategy_step_id
        teaching_progress["current_solution_question_id"] = strategy_question_id
        if strategy_step_id is not None:
            _require_known_solution_step_id(strategy_step_id, set(solution_steps))
            teaching_progress["current_lesson_plan_step_id"] = solution_steps[
                strategy_step_id
            ]["lesson_plan_step_id"]
        else:
            teaching_progress["current_lesson_plan_step_id"] = None
        if strategy_question_id is not None:
            _require_known_solution_question_id(
                strategy_question_id, set(solution_questions)
            )
            question_step, _ = solution_questions[strategy_question_id]
            if (
                strategy_step_id is not None
                and question_step["solution_step_id"] != strategy_step_id
            ):
                raise ValueError(
                    "Teaching node binds a Solution question to the wrong step."
                )
    if update.current_solution_step_id is not None:
        _require_known_solution_step_id(
            update.current_solution_step_id,
            set(solution_steps),
        )
        selected_solution_step = solution_steps[update.current_solution_step_id]
        selected_lesson_plan_step_id = selected_solution_step[
            "lesson_plan_step_id"
        ]
        if (
            update.current_lesson_plan_step_id is not None
            and update.current_lesson_plan_step_id
            != selected_lesson_plan_step_id
        ):
            raise ValueError(
                "Solution step and lesson plan step updates are inconsistent."
            )
        teaching_progress["current_solution_step_id"] = (
            update.current_solution_step_id
        )
        teaching_progress["current_lesson_plan_step_id"] = (
            selected_lesson_plan_step_id
        )
        if update.current_solution_question_id is None:
            step_questions = selected_solution_step.get("tutor_questions", [])
            teaching_progress["current_solution_question_id"] = (
                step_questions[0]["question_id"] if step_questions else None
            )
    if update.current_solution_question_id is not None:
        _require_known_solution_question_id(
            update.current_solution_question_id,
            set(solution_questions),
        )
        question_step, _ = solution_questions[
            update.current_solution_question_id
        ]
        question_step_id = question_step["solution_step_id"]
        if (
            update.current_solution_step_id is not None
            and update.current_solution_step_id != question_step_id
        ):
            raise ValueError(
                "Solution question and Solution step updates are inconsistent."
            )
        teaching_progress["current_solution_question_id"] = (
            update.current_solution_question_id
        )
        teaching_progress["current_solution_step_id"] = question_step_id
        teaching_progress["current_lesson_plan_step_id"] = question_step[
            "lesson_plan_step_id"
        ]
    if update.solution_step_summary is not None:
        teaching_progress["solution_step_summary"] = (
            update.solution_step_summary
        )

    _extend_unique(
        teaching_progress.setdefault("completed_lesson_plan_step_ids", []),
        _validated_step_ids(
            update.completed_lesson_plan_step_ids_to_add,
            allowed_step_ids,
        ),
        maximum_size=50,
    )
    _extend_unique(
        teaching_progress.setdefault("completed_solution_step_ids", []),
        _validated_solution_step_ids(
            update.completed_solution_step_ids_to_add,
            set(solution_steps),
        ),
        maximum_size=30,
    )
    _extend_unique(
        teaching_progress.setdefault("completed_solution_question_ids", []),
        _validated_solution_question_ids(
            update.completed_solution_question_ids_to_add,
            set(solution_questions),
        ),
        maximum_size=100,
    )

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

    _record_open_question_answer(
        next_state.setdefault("open_question_history", []),
        teaching_progress=teaching_progress,
        answer_summary=update.answered_open_question_summary,
        understanding=update.answered_open_question_understanding,
        assessment=update.answered_open_question_assessment,
        now=now,
    )

    if update.open_question is not None:
        teaching_progress["open_question"] = update.open_question
        _replace_open_question(
            next_state["open_question_history"],
            question=update.open_question,
            stage=teaching_progress.get("stage", "understand_task"),
            lesson_plan_step_id=teaching_progress.get(
                "current_lesson_plan_step_id"
            ),
            solution_step_id=teaching_progress.get(
                "current_solution_step_id"
            ),
            solution_question_id=teaching_progress.get(
                "current_solution_question_id"
            ),
            now=now,
        )

    if update.rolling_summary is not None:
        next_state["memory_meta"]["rolling_summary"] = update.rolling_summary

    if update.stage == "complete":
        teaching_progress["current_solution_question_id"] = None

    next_state["updated_at"] = now
    validate_teaching_state(next_state)
    return next_state


def apply_teaching_execution(
    current_teaching_state: Mapping[str, Any],
    execution: TeachingExecution,
) -> dict[str, Any]:
    """把一次执行 Agent 结果转换成受 Schema 约束的状态增量并合并。"""
    delta = execution.state_delta
    update = TeachingStateUpdate(**delta.model_dump(mode="python"))
    next_state = apply_teaching_state_update(current_teaching_state, update)
    evidence = next_state.setdefault("learning_evidence", [])
    known_ids = {item.get("evidence_id") for item in evidence}
    for item in execution.learning_evidence:
        if item.evidence_id not in known_ids and len(evidence) < 200:
            evidence.append(item.model_dump(mode="json"))
            known_ids.add(item.evidence_id)
    if execution.control_signal == "complete":
        next_state["teaching_progress"]["stage"] = "complete"
    next_state["updated_at"] = datetime.now(timezone.utc).isoformat()
    validate_teaching_state(next_state)
    return next_state


def validate_teaching_execution_against_state(
    current_teaching_state: Mapping[str, Any],
    execution: TeachingExecution,
) -> None:
    """在提交前校验执行 artifact 与当前策略、问题状态和转移图一致。"""
    history = current_teaching_state.get("open_question_history", [])
    open_questions = [item for item in history if item.get("status") == "open"]
    delta = execution.state_delta
    answer_fields = (
        delta.answered_open_question_summary,
        delta.answered_open_question_understanding,
        delta.answered_open_question_assessment,
    )
    has_answer = all(value is not None for value in answer_fields)

    if open_questions and not has_answer:
        raise ValueError(
            "The student message must assess and resolve the current open question."
        )
    if not open_questions and any(value is not None for value in answer_fields):
        raise ValueError(
            "Answer fields cannot be recorded because the state has no open question."
        )
    if not open_questions and execution.assessment != "not_applicable":
        raise ValueError(
            "A turn without an open question must use assessment='not_applicable'."
        )

    strategy = current_teaching_state.get("teaching_strategy") or {}
    nodes = {
        node.get("node_id"): node
        for node in strategy.get("nodes", [])
        if node.get("node_id") is not None
    }
    progress = current_teaching_state.get("teaching_progress", {})
    source_node_id = progress.get("current_strategy_node_id")
    source_node = nodes.get(source_node_id)
    target_node_id = delta.current_strategy_node_id or source_node_id

    if open_questions and source_node is not None:
        transitions = [
            item
            for item in source_node.get("transitions", [])
            if item.get("condition") == execution.assessment
        ]
        if len(transitions) == 1:
            transition = transitions[0]
            expected_node_id = transition.get("next_node_id")
            action = transition.get("action")
            if action == "replan" and execution.control_signal != "replan_required":
                raise ValueError("The selected strategy transition requires replanning.")
            if action == "complete" or (
                action == "advance" and expected_node_id is None
            ):
                if execution.control_signal != "complete":
                    raise ValueError("The terminal strategy transition must complete the turn.")
            elif action != "replan":
                if execution.control_signal != "continue":
                    raise ValueError("A non-terminal strategy transition must continue.")
                expected_target = expected_node_id or source_node_id
                if target_node_id != expected_target:
                    raise ValueError(
                        f"Assessment {execution.assessment!r} must transition to "
                        f"strategy node {expected_target!r}."
                    )

    if execution.control_signal != "continue":
        return
    target_node = nodes.get(target_node_id)
    if target_node is None:
        raise ValueError("A continuing turn must target a known teaching strategy node.")
    if (
        delta.current_solution_step_id is not None
        and delta.current_solution_step_id != target_node.get("solution_step_id")
    ):
        raise ValueError("The execution's Solution step does not match its target node.")
    if (
        delta.current_solution_question_id is not None
        and delta.current_solution_question_id
        != target_node.get("solution_question_id")
    ):
        raise ValueError("The execution's Solution question does not match its target node.")

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


def _require_known_step_id(
    step_id: str,
    allowed_step_ids: set[str],
) -> None:
    if step_id not in allowed_step_ids:
        raise ValueError(
            f"Unknown lesson plan step id {step_id!r}; "
            f"expected one of {sorted(allowed_step_ids)!r}."
        )


def _validated_step_ids(
    step_ids: list[str],
    allowed_step_ids: set[str],
) -> list[str]:
    for step_id in step_ids:
        _require_known_step_id(step_id, allowed_step_ids)
    return step_ids


def _require_known_solution_step_id(
    step_id: str,
    allowed_step_ids: set[str],
) -> None:
    if step_id not in allowed_step_ids:
        raise ValueError(
            f"Unknown Solution step id {step_id!r}; "
            f"expected one of {sorted(allowed_step_ids)!r}."
        )


def _validated_solution_step_ids(
    step_ids: list[str],
    allowed_step_ids: set[str],
) -> list[str]:
    for step_id in step_ids:
        _require_known_solution_step_id(step_id, allowed_step_ids)
    return step_ids


def _require_known_solution_question_id(
    question_id: str,
    allowed_question_ids: set[str],
) -> None:
    if question_id not in allowed_question_ids:
        raise ValueError(
            f"Unknown Solution question id {question_id!r}; "
            f"expected one of {sorted(allowed_question_ids)!r}."
        )


def _validated_solution_question_ids(
    question_ids: list[str],
    allowed_question_ids: set[str],
) -> list[str]:
    for question_id in question_ids:
        _require_known_solution_question_id(question_id, allowed_question_ids)
    return question_ids


def _replace_open_question(
    question_history: list[dict[str, Any]],
    *,
    question: str,
    stage: str,
    lesson_plan_step_id: str | None,
    solution_step_id: str | None,
    solution_question_id: str | None,
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
            "lesson_plan_step_id": lesson_plan_step_id,
            "solution_step_id": solution_step_id,
            "solution_question_id": solution_question_id,
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


def _record_open_question_answer(
    question_history: list[dict[str, Any]],
    *,
    teaching_progress: dict[str, Any],
    answer_summary: str | None,
    understanding: str | None,
    assessment: str | None,
    now: str,
) -> None:
    """将本轮学生对最近开放问题的回答与判断回填到历史记录。"""
    answer_fields = (answer_summary, understanding, assessment)
    if all(value is None for value in answer_fields):
        return
    if any(value is None for value in answer_fields):
        raise ValueError(
            "An open-question answer requires summary, understanding, and assessment."
        )

    open_questions = [
        item for item in question_history if item["status"] == "open"
    ]
    if not open_questions:
        raise ValueError("Cannot record an answer because there is no open question.")

    question = open_questions[-1]
    question["status"] = "answered"
    question["student_answer_summary"] = answer_summary
    question["agent_assessment"] = {
        "understanding": understanding,
        "summary": assessment,
    }
    question["resolved_at"] = now
    if teaching_progress.get("open_question") == question["question"]:
        teaching_progress["open_question"] = None
