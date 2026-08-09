"""虚拟教师配置的 JSON Schema。"""

from typing import Any

from jsonschema import Draft202012Validator

from susu_agent.schemas.format_checkers import ISO_DATETIME_FORMAT_CHECKER

SUBJECTS = ["math", "chinese", "english", "physics", "chemistry", "biology"]

TEACHER_MODEL_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "teacher_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
        },
        "schema_version": {
            "type": "integer",
            "minimum": 1,
        },
        "updated_at": {
            "type": "string",
            "format": "date-time",
        },
        "profile": {
            "type": "object",
            "properties": {
                "display_name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 50,
                },
                "role": {
                    "type": "string",
                    "enum": ["ai_tutor", "human_teacher"],
                },
                "subjects": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "uniqueItems": True,
                    "items": {"type": "string", "enum": SUBJECTS},
                },
                "target_grades": {
                    "type": "array",
                    "maxItems": 10,
                    "uniqueItems": True,
                    "items": {"type": "string", "maxLength": 50},
                },
            },
            "required": ["display_name", "role", "subjects"],
            "additionalProperties": False,
        },
        "teaching_policy": {
            "type": "object",
            "properties": {
                "primary_method": {
                    "type": "string",
                    "enum": ["socratic", "direct_instruction", "mixed"],
                },
                "answer_policy": {
                    "type": "string",
                    "enum": [
                        "guide_first",
                        "full_solution_after_trigger",
                        "full_solution_on_request",
                    ],
                },
                "framework_policy": {
                    "type": "string",
                    "enum": [
                        "required_when_available",
                        "use_general_when_missing",
                    ],
                },
                "max_primary_questions_per_turn": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3,
                },
                "hint_levels": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 6,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "enum": [
                            "restate_goal",
                            "remind_condition",
                            "remind_knowledge",
                            "suggest_method",
                            "show_partial_step",
                            "full_solution",
                        ],
                    },
                },
            },
            "required": [
                "primary_method",
                "answer_policy",
                "framework_policy",
                "max_primary_questions_per_turn",
                "hint_levels",
            ],
            "additionalProperties": False,
        },
        "frameworks": {
            "type": "array",
            "maxItems": 50,
            "items": {
                "type": "object",
                "properties": {
                    "framework_id": {
                        "type": "string",
                        "pattern": "^[a-z][a-z0-9_]*$",
                        "maxLength": 100,
                    },
                    "subject": {"type": "string", "enum": SUBJECTS},
                    "source_path": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 500,
                    },
                    "summary": {"type": "string", "maxLength": 500},
                },
                "required": ["framework_id", "subject", "source_path"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "teacher_id",
        "schema_version",
        "updated_at",
        "profile",
        "teaching_policy",
    ],
    "additionalProperties": False,
}

TEACHER_MODEL_VALIDATOR = Draft202012Validator(
    TEACHER_MODEL_SCHEMA,
    format_checker=ISO_DATETIME_FORMAT_CHECKER,
)


def validate_teacher_model(teacher_model: dict[str, Any]) -> None:
    """校验教师配置，不符合 schema 时抛出 ValidationError。"""
    TEACHER_MODEL_VALIDATOR.validate(teacher_model)
