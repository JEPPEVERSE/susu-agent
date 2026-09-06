"""学生模型的 JSON Schema。"""

from typing import Any

from jsonschema import Draft202012Validator

from susu_agent.schemas.format_checkers import ISO_DATETIME_FORMAT_CHECKER

SUBJECTS = ["math", "chinese", "english", "physics", "chemistry", "biology"]

STUDENT_MODEL_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "properties": {
        "student_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 100,
        },
        "schema_version": {
            "type": "integer",
            "minimum": 1,
        },
        "model_version": {
            "type": "integer",
            "minimum": 1,
        },
        "updated_at": {
            "type": "string",
            "format": "date-time",
        },
        "grade": {
            "type": "string",
            "minLength": 1,
            "maxLength": 50,
        },
        "identity": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "maxLength": 10},
                "age": {"type": "integer", "minimum": 0},
                "phone_number": {"type": "string", "maxLength": 20},
                "email_address": {
                    "type": "string",
                    "format": "email",
                    "maxLength": 254,
                },
                "school_name": {
                    "type": "object",
                    "properties": {
                        "junior_high": {"type": "string", "maxLength": 20},
                        "senior_high": {"type": "string", "maxLength": 20},
                        "college": {"type": "string", "maxLength": 20},
                    },
                    "required": ["senior_high"],
                    "additionalProperties": False,
                },
                "capability_map": {
                    "type": "object",
                    "properties": {
                        "good_at": {"type": "string", "enum": SUBJECTS},
                        "average": {"type": "string", "enum": SUBJECTS},
                        "bad_at": {"type": "string", "enum": SUBJECTS},
                    },
                    "required": ["good_at", "average", "bad_at"],
                    "additionalProperties": False,
                },
            },
            "required": ["name", "age"],
            "additionalProperties": False,
        },
        "personality": {
            "type": "object",
            "properties": {
                "learning_engagement": {
                    "type": "string",
                    "enum": ["unknown", "low", "medium", "high"],
                },
                "interaction_style": {
                    "type": "string",
                    "enum": ["unknown", "reserved", "balanced", "active"],
                },
                "notes": {"type": "string", "maxLength": 500},
            },
            "additionalProperties": True,
        },
        "learning_history": {
            "type": "object",
            "properties": {
                "concept_mastery": {
                    "type": "array",
                    "maxItems": 50,
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept_id": {
                                "type": "string",
                                "pattern": "^[a-z][a-z0-9_]*$",
                                "maxLength": 100,
                            },
                            "subject": {"type": "string", "enum": SUBJECTS},
                            "mastery": {
                                "type": "string",
                                "enum": [
                                    "unknown",
                                    "learning",
                                    "proficient",
                                    "mastered",
                                ],
                            },
                            "evidence_summary": {
                                "type": "string",
                                "maxLength": 300,
                            },
                            "updated_at": {
                                "type": "string",
                                "format": "date-time",
                            },
                        },
                        "required": [
                            "concept_id",
                            "subject",
                            "mastery",
                            "updated_at",
                        ],
                        "additionalProperties": False,
                    },
                },
                "persistent_misconceptions": {
                    "type": "array",
                    "maxItems": 20,
                    "items": {
                        "type": "object",
                        "properties": {
                            "concept_id": {
                                "type": "string",
                                "pattern": "^[a-z][a-z0-9_]*$",
                                "maxLength": 100,
                            },
                            "description": {
                                "type": "string",
                                "maxLength": 300,
                            },
                            "occurrences": {
                                "type": "integer",
                                "minimum": 1,
                            },
                            "last_seen_at": {
                                "type": "string",
                                "format": "date-time",
                            },
                        },
                        "required": [
                            "concept_id",
                            "description",
                            "occurrences",
                            "last_seen_at",
                        ],
                        "additionalProperties": False,
                    },
                },
                "recent_attempts": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {"type": "string", "maxLength": 500},
                },
            },
            "additionalProperties": True,
        },
        "score_map": {
            "type": "object",
            "properties": {
                "recent_scores": {
                    "type": "array",
                    "maxItems": 10,
                    "items": {
                        "type": "object",
                        "properties": {
                            "subject": {"type": "string", "enum": SUBJECTS},
                            "score": {"type": "number", "minimum": 0},
                            "max_score": {
                                "type": "number",
                                "exclusiveMinimum": 0,
                            },
                            "assessment_name": {
                                "type": "string",
                                "maxLength": 100,
                            },
                            "recorded_at": {
                                "type": "string",
                                "format": "date-time",
                            },
                        },
                        "required": [
                            "subject",
                            "score",
                            "max_score",
                            "recorded_at",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "additionalProperties": True,
        },
        "meta_knowledge_cards": {
            "type": "array",
            "maxItems": 100,
            "items": {
                "type": "object",
                "properties": {
                    "card_id": {
                        "type": "string",
                        "pattern": "^[a-z][a-z0-9_]*$",
                        "maxLength": 100,
                    },
                    "title": {"type": "string", "maxLength": 200},
                    "content": {"type": "string", "maxLength": 1_000},
                    "evidence_ids": {
                        "type": "array",
                        "maxItems": 30,
                        "uniqueItems": True,
                        "items": {"type": "string", "maxLength": 100},
                    },
                    "updated_at": {"type": "string", "format": "date-time"},
                },
                "required": ["card_id", "title", "content", "evidence_ids", "updated_at"],
                "additionalProperties": False,
            },
        },
        "prefered_style": {
            "type": "object",
            "properties": {
                "explanation_styles": {
                    "type": "array",
                    "maxItems": 3,
                    "uniqueItems": True,
                    "items": {
                        "type": "string",
                        "enum": [
                            "socratic",
                            "visual",
                            "step_by_step",
                            "example_first",
                            "concise",
                        ],
                    },
                },
                "preferred_pace": {
                    "type": "string",
                    "enum": ["unknown", "slow", "normal", "fast"],
                },
                "notes": {"type": "string", "maxLength": 500},
            },
            "additionalProperties": True,
        },
    },
    "required": [],
    "additionalProperties": False,
}

STUDENT_MODEL_VALIDATOR = Draft202012Validator(
    STUDENT_MODEL_SCHEMA,
    format_checker=ISO_DATETIME_FORMAT_CHECKER,
)


def validate_student_model(student_model: dict[str, Any]) -> None:
    """校验学生模型，不符合 schema 时抛出 ValidationError。"""
    STUDENT_MODEL_VALIDATOR.validate(student_model)
