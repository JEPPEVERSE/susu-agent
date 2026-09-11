"""v0.3 运行时所需的默认身份无关档案。"""

from datetime import datetime, timezone
from typing import Any


def default_teacher_model(teacher_id: str = "default_teacher") -> dict[str, Any]:
    return {
        "teacher_id": teacher_id,
        "schema_version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "personal_info": {"name": "Default Tutor"},
        "professional_profile": {"subjects": ["math"]},
        "teaching_style": {
            "primary_method": "mixed",
            "explanation_styles": ["step_by_step", "concise"],
            "interaction_style": "question_led",
            "feedback_style": "balanced",
            "teaching_pace": "adaptive",
        },
        "teaching_preferences": {
            "answer_policy": "guide_first",
            "framework_policy": "required_when_available",
            "max_primary_questions_per_turn": 1,
            "preferred_framework_ids": [],
        },
    }
