"""教师用户资料、教学习惯与偏好的 JSON Schema。"""

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
        "personal_info": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 50,
                },
                "age": {
                    "type": ["integer", "null"],
                    "minimum": 0,
                },
                "phone_number": {
                    "type": ["string", "null"],
                    "maxLength": 20,
                },
                "email_address": {
                    "type": ["string", "null"],
                    "format": "email",
                    "maxLength": 254,
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
        "professional_profile": {
            "type": "object",
            "properties": {
                "school_name": {
                    "type": ["string", "null"],
                    "maxLength": 100,
                },
                "title": {
                    "type": ["string", "null"],
                    "maxLength": 100,
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
                "years_of_experience": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 80,
                },
                "qualifications": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {"type": "string", "maxLength": 200},
                },
            },
            "required": ["subjects"],
            "additionalProperties": False,
        },
        "teaching_habits": {
            "type": "object",
            "properties": {
                "lesson_preparation_style": {
                    "type": "string",
                    "enum": ["framework_first", "problem_first", "mixed"],
                },
                "homework_policy": {
                    "type": "string",
                    "enum": ["none", "optional", "regular", "intensive"],
                },
                "assessment_frequency": {
                    "type": "string",
                    "enum": [
                        "unknown",
                        "per_lesson",
                        "weekly",
                        "unit_based",
                        "monthly",
                    ],
                },
                "notes": {"type": "string", "maxLength": 1_000},
            },
            "additionalProperties": False,
        },
        "teaching_style": {
            "type": "object",
            "properties": {
                "primary_method": {
                    "type": "string",
                    "enum": ["socratic", "direct_instruction", "mixed"],
                },
                "explanation_styles": {
                    "type": "array",
                    "maxItems": 3,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "enum": [
                            "visual",
                            "step_by_step",
                            "example_first",
                            "concise",
                        ],
                    },
                },
                "interaction_style": {
                    "type": "string",
                    "enum": ["question_led", "discussion", "lecture", "mixed"],
                },
                "feedback_style": {
                    "type": "string",
                    "enum": ["encouraging", "direct", "balanced"],
                },
                "teaching_pace": {
                    "type": "string",
                    "enum": ["slow", "normal", "fast", "adaptive"],
                },
            },
            "required": ["primary_method"],
            "additionalProperties": False,
        },
        "teaching_preferences": {
            "type": "object",
            "properties": {
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
                "preferred_framework_ids": {
                    "type": "array",
                    "maxItems": 50,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "pattern": "^[a-z][a-z0-9_]*$",
                        "maxLength": 100,
                    },
                },
            },
            "required": ["answer_policy", "framework_policy"],
            "additionalProperties": False,
        },
    },
    "required": [
        "teacher_id",
        "schema_version",
        "updated_at",
        "personal_info",
        "professional_profile",
        "teaching_style",
        "teaching_preferences",
    ],
    "additionalProperties": False,
}

TEACHER_MODEL_VALIDATOR = Draft202012Validator(
    TEACHER_MODEL_SCHEMA,
    format_checker=ISO_DATETIME_FORMAT_CHECKER,
)


def validate_teacher_model(teacher_model: dict[str, Any]) -> None:
    """校验教师用户资料，不符合 schema 时抛出 ValidationError。"""
    TEACHER_MODEL_VALIDATOR.validate(teacher_model)
