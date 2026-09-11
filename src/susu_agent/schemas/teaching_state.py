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
            "const": 7,
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
        "problem_representation": {
            "type": ["object", "null"],
            "$comment": "v0.3 题目结构投影，由 Pydantic 契约额外校验。",
        },
        "retrieval_cache": {
            "type": "object",
            "maxProperties": 30,
            "additionalProperties": {"type": "object"},
        },
        "memory_update_proposal_ids": {
            "type": "array",
            "maxItems": 100,
            "uniqueItems": True,
            "items": {"type": "string", "maxLength": 200},
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
                    "strategy_node_id": {
                        "type": ["string", "null"],
                        "maxLength": 100,
                    },
                    "solution_question_id": {
                        "type": ["string", "null"],
                        "maxLength": 100,
                    },
                    "question_card_id": {
                        "type": ["string", "null"],
                        "maxLength": 200,
                    },
                    "retrieval_evidence_ids": {
                        "type": "array",
                        "maxItems": 30,
                        "uniqueItems": True,
                        "items": {"type": "string", "maxLength": 200},
                    },
                    "target_checkpoint_indices": {
                        "type": "array",
                        "maxItems": 10,
                        "uniqueItems": True,
                        "items": {"type": "integer", "minimum": 0},
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
                    "assessment": {
                        "type": "string",
                        "enum": [
                            "not_answered",
                            "no_idea",
                            "incorrect",
                            "partially_correct",
                            "correct",
                            "unclear",
                            "student_requests_solution"
                        ],
                    },
                    "assessment_reason": {
                        "type": "string",
                        "maxLength": 500,
                    },
                    "resolved_at": {
                        "type": ["string", "null"],
                        "format": "date-time",
                    },
                },
                "required": [
                    "question_id",
                    "question",
                    "strategy_node_id",
                    "solution_question_id",
                    "target_checkpoint_indices",
                    "status",
                    "asked_at",
                    "student_answer_summary",
                    "assessment",
                    "assessment_reason",
                    "resolved_at",
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
                "completed_strategy_node_ids": {
                    "type": "array",
                    "maxItems": 100,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^teach_[0-9]+$",
                        "maxLength": 100,
                    },
                },
                "satisfied_checkpoint_ids": {
                    "type": "array",
                    "maxItems": 1_000,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^teach_[0-9]+:checkpoint_[0-9]+$",
                        "maxLength": 150,
                    },
                },
                "attempts_by_node": {
                    "type": "object",
                    "patternProperties": {
                        "^teach_[0-9]+$": {"type": "integer", "minimum": 0}
                    },
                    "additionalProperties": False,
                },
                "hint_indices_by_node": {
                    "type": "object",
                    "patternProperties": {
                        "^teach_[0-9]+$": {"type": "integer", "minimum": 0}
                    },
                    "additionalProperties": False,
                },
            },
            "required": [
                "current_strategy_node_id",
                "completed_strategy_node_ids",
                "satisfied_checkpoint_ids",
                "attempts_by_node",
                "hint_indices_by_node",
            ],
            "additionalProperties": False,
        },
        "updated_at": {
            "type": "string",
            "format": "date-time",
        },

        "conversation_summary": {
            "type": "string",
            "maxLength": 2_000,
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
        "v03_meta": {
            "type": "object",
            "properties": {
                "architecture_version": {"type": "string", "const": "0.3"},
                "memory_enabled": {"type": "boolean"},
                "solution_revision": {"type": "integer", "minimum": 0},
                "summary_completed": {"type": "boolean"},
            },
            "required": [
                "architecture_version",
                "memory_enabled",
                "solution_revision",
                "summary_completed"
            ],
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
        "updated_at",
        "conversation_summary",
        "v03_meta",
        "problem_representation",
        "retrieval_cache",
        "memory_update_proposal_ids",
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
    if state.get("problem_representation") is not None:
        from susu_agent.schemas.problem_representation import ProblemRepresentation

        ProblemRepresentation.model_validate(state["problem_representation"])
    from susu_agent.schemas.memory import RetrievalResult

    for value in state.get("retrieval_cache", {}).values():
        RetrievalResult.model_validate(value)
    _validate_open_question_invariants(state)


def _validate_open_question_invariants(state: dict[str, Any]) -> None:
    history = state["open_question_history"]
    question_ids = [item["question_id"] for item in history]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("Open-question history contains duplicate question ids.")

    open_questions = [item for item in history if item["status"] == "open"]
    if len(open_questions) > 1:
        raise ValueError("Teaching state cannot contain more than one open question.")

    for item in history:
        status = item["status"]
        assessment = item["assessment"]
        if status == "open":
            if (
                item["student_answer_summary"] is not None
                or assessment != "not_answered"
                or item["assessment_reason"]
                or item.get("resolved_at") is not None
            ):
                raise ValueError("An open question cannot contain resolved-answer data.")
        elif status == "answered":
            if (
                item["student_answer_summary"] is None
                or assessment == "not_answered"
                or not item["assessment_reason"]
                or item.get("resolved_at") is None
            ):
                raise ValueError("An answered question requires answer and resolution data.")
