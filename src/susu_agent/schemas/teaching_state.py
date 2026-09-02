from typing import Any

from jsonschema import Draft202012Validator

from susu_agent.schemas.format_checkers import ISO_DATETIME_FORMAT_CHECKER


TEACHING_STATE_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "session_id": {
            "type": "string",
            "minLength": 1,
        },

        "schema_version": {
            "type": "integer",
            "const": 3,
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
            },
            "required": ["problem_statement"],
            "additionalProperties": False,
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
                "stage",
                "current_lesson_plan_step_id",
                "completed_lesson_plan_step_ids",
                "lesson_plan_step_summary",
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
    },
    "required": [
        "session_id",
        "schema_version",
        "lesson_plan",
        "open_question_history",
        "teaching_progress",
        "student_model",
        "updated_at",
        "memory_meta",
    ],
    "additionalProperties": False,
}

TEACHING_STATE_VALIDATOR = Draft202012Validator(
    TEACHING_STATE_SCHEMA,
    format_checker=ISO_DATETIME_FORMAT_CHECKER,
)


def validate_teaching_state(state: dict[str, Any]) -> None:
    """校验教学状态，不符合 schema 时抛出 ValidationError。"""
    TEACHING_STATE_VALIDATOR.validate(state)
