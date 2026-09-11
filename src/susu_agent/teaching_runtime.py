"""v0.3 TeachingExecution 的确定性状态转移与记忆引用校验。"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from susu_agent.schemas.teaching_state import validate_teaching_state
from susu_agent.schemas.v03 import (
    LearningEvidence,
    TeachingExecution,
    TeachingStrategy,
)


MAX_NODE_ATTEMPTS = 3
_NON_MASTERY_ASSESSMENTS = {
    "no_idea",
    "incorrect",
    "partially_correct",
    "unclear",
    "student_requests_solution",
}


@dataclass(frozen=True, slots=True)
class ExecutionDecision:
    source_node_id: str | None
    target_node_id: str | None
    transition_condition: str
    action: str
    control_signal: Literal["continue", "replan_required", "complete"]
    forced_advance: bool = False


def checkpoint_id(node_id: str, checkpoint_index: int) -> str:
    return f"{node_id}:checkpoint_{checkpoint_index}"


def render_teaching_response(execution: TeachingExecution) -> str:
    """由唯一的结构化问题字段组装学生可见回复。"""
    parts = [execution.feedback.strip()]
    if execution.state_delta.open_question is not None:
        parts.append(execution.state_delta.open_question.strip())
    response = "\n\n".join(part for part in parts if part)
    if not response:
        raise ValueError("A teaching turn produced an empty student response.")
    if len(response) > 8_000:
        raise ValueError("The rendered teaching response is too long.")
    return response


def validate_strategy_runtime_contract(
    strategy: TeachingStrategy | Mapping[str, Any],
) -> TeachingStrategy:
    """验证策略图具备确定性执行和有限退出所需的全部边。"""
    parsed = (
        strategy
        if isinstance(strategy, TeachingStrategy)
        else TeachingStrategy.model_validate(strategy)
    )
    if not parsed.nodes or parsed.initial_node_id is None:
        raise ValueError("A runnable teaching strategy requires an initial node.")
    required_conditions = {
        "correct",
        "partially_correct",
        "incorrect",
        "no_idea",
        "unclear",
        "student_requests_solution",
    }
    for node in parsed.nodes:
        conditions = {transition.condition for transition in node.transitions}
        if conditions != required_conditions:
            raise ValueError(
                f"Teaching strategy node {node.node_id!r} must define exactly "
                "one transition for every runtime assessment."
            )
        if node.teaching_action == "ask_question" and not node.answer_checkpoints:
            raise ValueError(
                f"Question node {node.node_id!r} requires answer checkpoints."
            )
        correct_transition = next(
            transition
            for transition in node.transitions
            if transition.condition == "correct"
        )
        if correct_transition.action not in {"advance", "complete"}:
            raise ValueError(
                f"Teaching strategy node {node.node_id!r} must leave the node "
                "after a correct answer."
            )
        if correct_transition.next_node_id == node.node_id:
            raise ValueError(
                f"Teaching strategy node {node.node_id!r} cannot self-loop "
                "on a correct answer."
            )
    return parsed


def resolve_execution_decision(
    current_teaching_state: Mapping[str, Any],
    execution: TeachingExecution,
) -> ExecutionDecision:
    """聚合跨轮检查点并执行重试上限，Agent 不拥有状态转移权。"""
    nodes = _strategy_nodes(current_teaching_state)
    progress = current_teaching_state.get("teaching_progress", {})
    source_node_id = progress.get("current_strategy_node_id")
    source_node = nodes.get(source_node_id)
    active_question = _active_question(current_teaching_state)
    if active_question is None:
        return ExecutionDecision(
            source_node_id=source_node_id,
            target_node_id=source_node_id,
            transition_condition="not_applicable",
            action="ask_question",
            control_signal="continue",
        )
    if source_node is None:
        raise ValueError("An answered question requires a current strategy node.")

    satisfied = _satisfied_indices(current_teaching_state, source_node_id)
    satisfied.update(
        _validated_checkpoint_additions(execution, source_node, active_question)
    )
    checkpoint_count = len(source_node.get("answer_checkpoints", []))
    if checkpoint_count and len(satisfied) == checkpoint_count:
        condition = "correct"
    elif execution.assessment == "correct":
        condition = "partially_correct"
    else:
        condition = execution.assessment

    attempts = progress.get("attempts_by_node", {}).get(source_node_id, 0) + 1
    forced_advance = condition in _NON_MASTERY_ASSESSMENTS and attempts >= MAX_NODE_ATTEMPTS
    transition_condition = "correct" if forced_advance else condition
    transition = _require_transition(source_node, transition_condition)
    action = transition.get("action")
    target_node_id = transition.get("next_node_id")
    if action == "replan":
        control_signal = "replan_required"
        target_node_id = source_node_id
    elif action == "complete" or (action == "advance" and target_node_id is None):
        control_signal = "complete"
        target_node_id = None
    else:
        control_signal = "continue"
        target_node_id = target_node_id or source_node_id
    return ExecutionDecision(
        source_node_id=source_node_id,
        target_node_id=target_node_id,
        transition_condition=transition_condition,
        action=str(action),
        control_signal=control_signal,
        forced_advance=forced_advance,
    )


def validate_teaching_execution_against_state(
    current_teaching_state: Mapping[str, Any],
    execution: TeachingExecution,
) -> ExecutionDecision:
    """校验回答、检查点、转移、循环边界与学习证据。"""
    active_question = _active_question(current_teaching_state)
    delta = execution.state_delta
    answer_fields = (
        delta.answered_open_question_summary,
        delta.answered_open_question_feedback,
    )
    if active_question is not None:
        if execution.assessment == "not_applicable" or not all(answer_fields):
            raise ValueError("The active question requires assessment and answer summary.")
    else:
        if execution.assessment != "not_applicable" or any(answer_fields):
            raise ValueError("A turn without an open question must be unassessed.")
        if delta.satisfied_checkpoint_indices_to_add:
            raise ValueError("A turn without an answer cannot satisfy checkpoints.")

    decision = resolve_execution_decision(current_teaching_state, execution)
    if decision.control_signal == "continue":
        if delta.open_question is None:
            raise ValueError("A continuing turn must ask exactly one question.")
    elif delta.open_question is not None:
        raise ValueError("A terminal or replanning turn cannot open a question.")

    nodes = _strategy_nodes(current_teaching_state)
    target_node = nodes.get(decision.target_node_id)
    targets = delta.open_question_target_checkpoint_indices
    if delta.open_question is not None:
        if target_node is None:
            raise ValueError("An open question must target a known strategy node.")
        checkpoint_count = len(target_node.get("answer_checkpoints", []))
        if len(targets) != len(set(targets)) or any(
            index < 0 or index >= checkpoint_count for index in targets
        ):
            raise ValueError("Open-question checkpoint targets are invalid.")
        if target_node.get("teaching_action") == "ask_question" and checkpoint_count and not targets:
            raise ValueError("A question node must target at least one checkpoint.")
        already_satisfied = _satisfied_indices(
            current_teaching_state, decision.target_node_id
        )
        if decision.target_node_id == decision.source_node_id and active_question:
            already_satisfied.update(
                _validated_checkpoint_additions(
                    execution, target_node, active_question
                )
            )
        if any(index in already_satisfied for index in targets):
            raise ValueError("The next question must target an unsatisfied checkpoint.")

    _validate_learning_evidence(
        current_teaching_state,
        execution.learning_evidence,
        active_question,
        decision.source_node_id,
    )
    _validate_execution_memory_references(current_teaching_state, execution)
    return decision


def _validate_execution_memory_references(
    state: Mapping[str, Any], execution: TeachingExecution
) -> None:
    cache = state.get("retrieval_cache", {}).get("execution", {})
    retrieved = {
        item.get("memory_id"): item.get("memory_type")
        for item in cache.get("evidence", [])
        if isinstance(item, Mapping)
    }
    referenced = set(execution.retrieval_evidence_ids)
    referenced.update(execution.diagnosed_misconception_card_ids)
    for evidence in execution.learning_evidence:
        referenced.update(evidence.retrieval_evidence_ids)
        referenced.update(evidence.misconception_card_ids)
    unknown = referenced - set(retrieved)
    if unknown:
        raise ValueError(
            f"Teaching execution references unreturned memory: {sorted(unknown)!r}."
        )
    invalid = {
        memory_id
        for memory_id in execution.diagnosed_misconception_card_ids
        if retrieved.get(memory_id) != "misconception_card"
    }
    invalid.update(
        memory_id
        for evidence in execution.learning_evidence
        for memory_id in evidence.misconception_card_ids
        if retrieved.get(memory_id) != "misconception_card"
    )
    if invalid:
        raise ValueError(
            f"Diagnosis references non-Misconception Cards: {sorted(invalid)!r}."
        )


def apply_teaching_execution(
    current_teaching_state: Mapping[str, Any],
    execution: TeachingExecution,
) -> dict[str, Any]:
    """按代码计算出的决策更新状态，不接受 Agent 提交游标。"""
    decision = validate_teaching_execution_against_state(
        current_teaching_state, execution
    )
    next_state = deepcopy(dict(current_teaching_state))
    progress = next_state["teaching_progress"]
    delta = execution.state_delta
    now = datetime.now(timezone.utc).isoformat()
    active_question = _active_question(next_state)

    if active_question is not None:
        source_node_id = decision.source_node_id
        source_node = _strategy_nodes(next_state)[source_node_id]
        additions = _validated_checkpoint_additions(
            execution, source_node, active_question
        )
        _record_open_question_answer(
            next_state["open_question_history"],
            summary=delta.answered_open_question_summary or "",
            assessment=execution.assessment,
            reason=delta.answered_open_question_feedback or "",
            now=now,
        )
        attempts = progress.setdefault("attempts_by_node", {})
        attempts[source_node_id] = attempts.get(source_node_id, 0) + 1
        satisfied_ids = progress.setdefault("satisfied_checkpoint_ids", [])
        for index in additions:
            value = checkpoint_id(source_node_id, index)
            if value not in satisfied_ids:
                satisfied_ids.append(value)

    if decision.source_node_id is not None and (
        decision.target_node_id != decision.source_node_id
        or decision.control_signal == "complete"
    ):
        completed = progress.setdefault("completed_strategy_node_ids", [])
        if decision.source_node_id not in completed:
            completed.append(decision.source_node_id)

    progress["current_strategy_node_id"] = decision.target_node_id
    if decision.source_node_id is not None and decision.action in {
        "retry",
        "give_hint",
        "explain",
    }:
        hint_indices = progress.setdefault("hint_indices_by_node", {})
        source_node = _strategy_nodes(next_state)[decision.source_node_id]
        ladder_size = len(source_node.get("hint_ladder", []))
        hint_indices[decision.source_node_id] = min(
            hint_indices.get(decision.source_node_id, 0) + 1,
            ladder_size,
        )

    if delta.open_question is not None:
        _append_open_question(
            next_state,
            question=delta.open_question,
            strategy_node_id=decision.target_node_id,
            target_checkpoint_indices=delta.open_question_target_checkpoint_indices,
            now=now,
        )
    if delta.conversation_summary is not None:
        next_state["conversation_summary"] = delta.conversation_summary

    evidence = next_state.setdefault("learning_evidence", [])
    known_ids = {item.get("evidence_id") for item in evidence}
    for item in execution.learning_evidence:
        if item.evidence_id not in known_ids and len(evidence) < 200:
            evidence.append(item.model_dump(mode="json"))
            known_ids.add(item.evidence_id)
    next_state["updated_at"] = now
    validate_teaching_state(next_state)
    return next_state


def _strategy_nodes(state: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    strategy = state.get("teaching_strategy") or {}
    return {
        node["node_id"]: node
        for node in strategy.get("nodes", [])
        if isinstance(node, Mapping) and node.get("node_id") is not None
    }


def _active_question(state: Mapping[str, Any]) -> Mapping[str, Any] | None:
    active = [
        item
        for item in state.get("open_question_history", [])
        if item.get("status") == "open"
    ]
    if len(active) > 1:
        raise ValueError("Teaching state contains multiple open questions.")
    return active[0] if active else None


def _satisfied_indices(state: Mapping[str, Any], node_id: str | None) -> set[int]:
    if node_id is None:
        return set()
    prefix = f"{node_id}:checkpoint_"
    return {
        int(value.removeprefix(prefix))
        for value in state.get("teaching_progress", {}).get(
            "satisfied_checkpoint_ids", []
        )
        if value.startswith(prefix)
    }


def _validated_checkpoint_additions(
    execution: TeachingExecution,
    source_node: Mapping[str, Any],
    active_question: Mapping[str, Any] | None,
) -> set[int]:
    raw_additions = execution.state_delta.satisfied_checkpoint_indices_to_add
    additions = set(raw_additions)
    if len(additions) != len(raw_additions):
        raise ValueError("Satisfied checkpoint indices must be unique.")
    checkpoint_count = len(source_node.get("answer_checkpoints", []))
    if any(index < 0 or index >= checkpoint_count for index in additions):
        raise ValueError("Satisfied checkpoint index is outside the current node.")
    targets = set(
        active_question.get("target_checkpoint_indices", [])
        if active_question is not None
        else []
    )
    if additions - targets:
        raise ValueError("An answer can only satisfy checkpoints asked this turn.")
    if execution.assessment == "correct":
        additions.update(targets)
    elif execution.assessment in {
        "no_idea",
        "incorrect",
        "unclear",
        "student_requests_solution",
        "not_applicable",
    } and additions:
        raise ValueError("This assessment cannot satisfy a checkpoint.")
    return additions


def _require_transition(
    node: Mapping[str, Any], condition: str
) -> Mapping[str, Any]:
    matches = [
        item
        for item in node.get("transitions", [])
        if item.get("condition") == condition
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Strategy node {node.get('node_id')!r} requires exactly one "
            f"transition for {condition!r}."
        )
    return matches[0]


def _validate_learning_evidence(
    state: Mapping[str, Any],
    evidence: list[LearningEvidence],
    active_question: Mapping[str, Any] | None,
    source_node_id: str | None,
) -> None:
    evidence_ids = [item.evidence_id for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("Learning evidence ids must be unique in a turn.")
    source_node = _strategy_nodes(state).get(source_node_id)
    solution_step_id = source_node.get("solution_step_id") if source_node else None
    solution = state.get("solution") or {}
    source_step = next(
        (
            step
            for step in solution.get("steps", [])
            if step.get("solution_step_id") == solution_step_id
        ),
        None,
    )
    allowed_concepts = set(source_step.get("concept_ids", []) if source_step else [])
    active_question_id = active_question.get("question_id") if active_question else None
    for item in evidence:
        if item.concept_id not in allowed_concepts:
            raise ValueError("Learning evidence references a concept outside the current step.")
        if item.source_question_id not in {None, active_question_id}:
            raise ValueError("Learning evidence must reference the active history question.")


def _record_open_question_answer(
    history: list[dict[str, Any]],
    *,
    summary: str,
    assessment: str,
    reason: str,
    now: str,
) -> None:
    question = next(item for item in reversed(history) if item["status"] == "open")
    question["status"] = "answered"
    question["student_answer_summary"] = summary
    question["assessment"] = assessment
    question["assessment_reason"] = reason
    question["resolved_at"] = now


def _append_open_question(
    state: dict[str, Any],
    *,
    question: str,
    strategy_node_id: str | None,
    target_checkpoint_indices: list[int],
    now: str,
) -> None:
    history = state.setdefault("open_question_history", [])
    if any(item["status"] == "open" for item in history):
        raise ValueError("Cannot create a second open question.")
    node = _strategy_nodes(state).get(strategy_node_id)
    next_number = max(
        (
            int(item["question_id"].removeprefix("question_"))
            for item in history
        ),
        default=-1,
    ) + 1
    history.append(
        {
            "question_id": f"question_{next_number}",
            "question": question,
            "strategy_node_id": strategy_node_id,
            "solution_question_id": node.get("solution_question_id") if node else None,
            "question_card_id": node.get("question_card_id") if node else None,
            "retrieval_evidence_ids": (
                list(node.get("retrieval_evidence_ids", [])) if node else []
            ),
            "target_checkpoint_indices": list(target_checkpoint_indices),
            "status": "open",
            "asked_at": now,
            "student_answer_summary": None,
            "assessment": "not_answered",
            "assessment_reason": "",
            "resolved_at": None,
        }
    )
