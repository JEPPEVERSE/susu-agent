from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator

from susu_agent.schemas.format_checkers import ISO_DATETIME_FORMAT_CHECKER
from susu_agent.schemas.solution import SOLUTION_SCHEMA


_EMBEDDED_SOLUTION_SCHEMA = deepcopy(SOLUTION_SCHEMA)
_SOLUTION_DEFINITIONS = _EMBEDDED_SOLUTION_SCHEMA.pop("$defs", {})


TEACHING_STATE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$defs": _SOLUTION_DEFINITIONS,
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "minLength": 1,
        },

        "schema_version": {
            "type": "integer",
            "const": 6,
        },

        "lesson_plan": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "pattern": "^[a-z][a-z0-9_-]*$",
                    "maxLength": 100,
                },
                "manifest_schema_version": {
                    "type": "integer",
                    "minimum": 1,
                },
                "lesson_plan_version": {
                    "type": "string",
                    "pattern": "^[0-9]+\\.[0-9]+\\.[0-9]+$",
                },
                "step_ids": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^[A-Za-z][A-Za-z0-9_-]{0,99}$",
                    },
                },
                "instruction_sources": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 500},
                },
                "context_sources": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 500},
                },
                "content_digest": {
                    "type": "string",
                    "pattern": "^[a-f0-9]{64}$",
                },
            },
            "required": [
                "subject",
                "manifest_schema_version",
                "lesson_plan_version",
                "step_ids",
                "instruction_sources",
                "context_sources",
                "content_digest",
            ],
            "additionalProperties": False,
        },

        "original_problem": {
            "type": "object",
            "properties": {
                "problem_statement": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 8_000,
                },
                "reference_answer": {
                    "type": ["string", "null"],
                    "$comment": "仅作内部参考，不能直接拼接到面向学生的 Prompt。",
                    "maxLength": 4_000,
                },
                "main_info": {
                    "type": "object",
                    "properties": {
                        "discipline": {"type": "string", "maxLength": 100},
                        "section": {"type": "string", "maxLength": 100},
                        "sub_section": {"type": "string", "maxLength": 100},
                        "summary": {"type": "string", "maxLength": 500},
                    },
                    "additionalProperties": False,
                },
                "status": {
                    "type": "string",
                    "enum": [
                        "pending",
                        "solved",
                        "incomplete",
                        "ambiguous",
                        "unsupported"
                    ],
                },
                "clarification_questions": {
                    "type": "array",
                    "maxItems": 5,
                    "items": {"type": "string", "minLength": 1, "maxLength": 1_000},
                },
                "clarification_context": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {"type": "string", "minLength": 1, "maxLength": 2_000},
                },
            },
            "required": [
                "problem_statement",
                "status",
                "clarification_questions",
                "clarification_context"
            ],
            "additionalProperties": False,
        },

        "solution": {
            "anyOf": [
                _EMBEDDED_SOLUTION_SCHEMA,
                {"type": "null"},
            ],
            "$comment": "由数学解题 Agent 生成的会话级内部解题路线。",
        },
        "verification_report": {
            "type": ["object", "null"],
            "$comment": "由 VerificationReport Pydantic 模型执行严格校验。",
        },
        "teaching_strategy": {
            "type": ["object", "null"],
            "$comment": "由 TeachingStrategy Pydantic 模型执行严格校验。",
        },
        "learning_evidence": {
            "type": "array",
            "maxItems": 200,
            "items": {"type": "object"},
        },

        "open_question_history": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question_id": {
                        "type": "string",
                        "pattern": "^question_[0-9]+$",
                        "maxLength": 100,
                    },
                    "question": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 1_000,
                    },
                    "stage": {
                        "type": "string",
                        "enum": [
                            "understand_task",
                            "recall_knowledge",
                            "make_plan",
                            "execute",
                            "verify",
                            "complete",
                        ],
                    },
                    "lesson_plan_step_id": {
                        "type": ["string", "null"],
                        "maxLength": 200,
                    },
                    "solution_step_id": {
                        "type": ["string", "null"],
                        "maxLength": 100,
                    },
                    "solution_question_id": {
                        "type": ["string", "null"],
                        "maxLength": 100,
                    },
                    "status": {
                        "type": "string",
                        "enum": ["open", "answered", "superseded", "abandoned"],
                    },
                    "asked_at": {
                        "type": "string",
                        "format": "date-time",
                    },
                    "student_answer_summary": {
                        "type": ["string", "null"],
                        "maxLength": 500,
                    },
                    "agent_assessment": {
                        "type": "object",
                        "properties": {
                            "understanding": {
                                "type": "string",
                                "enum": [
                                    "not_answered",
                                    "no_idea",
                                    "incorrect",
                                    "partially_correct",
                                    "correct",
                                    "unclear",
                                ],
                            },
                            "summary": {
                                "type": "string",
                                "maxLength": 500,
                            },
                        },
                        "required": ["understanding", "summary"],
                        "additionalProperties": False,
                    },
                    "resolved_at": {
                        "type": ["string", "null"],
                        "format": "date-time",
                    },
                },
                "required": [
                    "question_id",
                    "question",
                    "stage",
                    "lesson_plan_step_id",
                    "solution_step_id",
                    "solution_question_id",
                    "status",
                    "asked_at",
                    "student_answer_summary",
                    "agent_assessment",
                ],
                "additionalProperties": False,
            },
        },

        "teaching_progress": {
            "type": "object",
            "properties": {
                "current_strategy_node_id": {
                    "type": ["string", "null"],
                    "maxLength": 100,
                },
                "stage": {
                    "type": "string",
                    "enum": [
                        "understand_task",
                        "recall_knowledge",
                        "make_plan",
                        "execute",
                        "verify",
                        "complete",
                    ],
                },
                "current_lesson_plan_step_id": {
                    "type": ["string", "null"],
                    "maxLength": 200,
                },
                "completed_lesson_plan_step_ids": {
                    "type": "array",
                    "maxItems": 50,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 200,
                    },
                },
                "lesson_plan_step_summary": {
                    "type": "string",
                    "maxLength": 1_000,
                },
                "current_solution_step_id": {
                    "type": ["string", "null"],
                    "maxLength": 100,
                },
                "completed_solution_step_ids": {
                    "type": "array",
                    "maxItems": 30,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^step_[0-9]+$",
                        "maxLength": 100,
                    },
                },
                "solution_step_summary": {
                    "type": "string",
                    "maxLength": 1_000,
                },
                "current_solution_question_id": {
                    "type": ["string", "null"],
                    "maxLength": 100,
                },
                "completed_solution_question_ids": {
                    "type": "array",
                    "maxItems": 100,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^question_[0-9]+$",
                        "maxLength": 100,
                    },
                },
                "hints_num": {
                    "type": "integer",
                    "minimum": 0,
                },
                "hint_level": {
                    "type": "string",
                    "enum": ["none", "light", "medium", "strong"],
                },
                "confirmed_steps": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 100,
                    },
                },
                "open_question": {
                    "type": ["string", "null"],
                    "maxLength": 1_000,
                },
                "next_teacher_action": {
                    "type": "string",
                    "enum": [
                        "ask_question",
                        "give_hint",
                        "explain",
                        "verify_answer",
                    ],
                },
                "summary": {"type": "string", "maxLength": 1_000},
            },
            "required": [
                "current_strategy_node_id",
                "stage",
                "current_lesson_plan_step_id",
                "completed_lesson_plan_step_ids",
                "lesson_plan_step_summary",
                "current_solution_step_id",
                "completed_solution_step_ids",
                "solution_step_summary",
                "current_solution_question_id",
                "completed_solution_question_ids",
                "hints_num",
                "confirmed_steps",
                "next_teacher_action",
            ],
            "additionalProperties": False,
        },
        "student_model": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "object",
                    "properties": {
                        "known_concepts": {
                            "type": "array",
                            "maxItems": 20,
                            "items": {"type": "string", "maxLength": 100},
                        },
                        "recent_attempts": {
                            "type": "array",
                            "maxItems": 3,
                            "items": {"type": "string", "maxLength": 500},
                        },
                        "current_step_confidence": {
                            "type": "string",
                            "enum": ["unknown", "low", "medium", "high"],
                        },
                        "main_misconceptions": {
                            "type": "array",
                            "maxItems": 10,
                            "items": {"type": "string", "maxLength": 200},
                        },
                    },
                    "additionalProperties": False,
                },
            },
            "additionalProperties": False,
        },

        "updated_at": {
            "type": "string",
            "format": "date-time",
        },

        "memory_meta": {
            "type": "object",
            "properties": {
                "last_processed_message_id": {
                    "type": ["string", "null"],
                    "maxLength": 200,
                },
                "last_compacted_message_id": {
                    "type": ["string", "null"],
                    "maxLength": 200,
                },
                "rolling_summary": {
                    "type": "string",
                    "maxLength": 2_000,
                },
            },
            "required": [
                "last_processed_message_id",
                "last_compacted_message_id",
                "rolling_summary",
            ],
            "additionalProperties": False,
        },
        "v02_meta": {
            "type": "object",
            "properties": {
                "architecture_version": {"type": "string", "const": "0.2"},
                "solution_revision": {"type": "integer", "minimum": 0},
                "summary_completed": {"type": "boolean"},
            },
            "required": ["architecture_version", "solution_revision", "summary_completed"],
            "additionalProperties": False,
        },
        "personal_ai": {
            "type": "object",
            "properties": {
                "principal_id": {"type": ["string", "null"], "maxLength": 200},
                "consent_scope": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 100},
                },
                "data_classification": {
                    "type": "string",
                    "enum": ["internal", "personal", "sensitive"],
                },
                "encryption_ref": {"type": ["string", "null"], "maxLength": 500},
            },
            "required": ["principal_id", "consent_scope", "data_classification", "encryption_ref"],
            "additionalProperties": False,
        },
    },
    "required": [
        "session_id",
        "schema_version",
        "lesson_plan",
        "solution",
        "verification_report",
        "teaching_strategy",
        "learning_evidence",
        "open_question_history",
        "teaching_progress",
        "student_model",
        "updated_at",
        "memory_meta",
        "v02_meta",
        "personal_ai",
    ],
    "additionalProperties": False,
}

TEACHING_STATE_VALIDATOR = Draft202012Validator(
    TEACHING_STATE_SCHEMA,
    format_checker=ISO_DATETIME_FORMAT_CHECKER,
)


def validate_teaching_state(state: dict[str, Any]) -> None:
    """校验教学状态的 JSON 结构及跨字段运行时不变量。"""
    TEACHING_STATE_VALIDATOR.validate(state)
    _validate_open_question_invariants(state)


def _validate_open_question_invariants(state: dict[str, Any]) -> None:
    history = state["open_question_history"]
    question_ids = [item["question_id"] for item in history]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("Open-question history contains duplicate question ids.")

    open_questions = [item for item in history if item["status"] == "open"]
    if len(open_questions) > 1:
        raise ValueError("Teaching state cannot contain more than one open question.")

    progress_question = state["teaching_progress"].get("open_question")
    if open_questions:
        if progress_question != open_questions[0]["question"]:
            raise ValueError(
                "teaching_progress.open_question must match the open history item."
            )
    elif progress_question is not None:
        raise ValueError(
            "teaching_progress.open_question requires an open history item."
        )

    for item in history:
        status = item["status"]
        understanding = item["agent_assessment"]["understanding"]
        if status == "open":
            if (
                item["student_answer_summary"] is not None
                or understanding != "not_answered"
                or item.get("resolved_at") is not None
            ):
                raise ValueError("An open question cannot contain resolved-answer data.")
        elif status == "answered":
            if (
                item["student_answer_summary"] is None
                or understanding == "not_answered"
                or item.get("resolved_at") is None
            ):
                raise ValueError("An answered question requires answer and resolution data.")
