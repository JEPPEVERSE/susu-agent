"""在本地 StudentModel 数据库中创建可重复使用的 v0.2 测试学生。"""

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from susu_agent.repositories.student_model_repository import StudentModelRepository


def build_test_student(student_id: str) -> dict[str, object]:
    now = datetime.now(timezone.utc).isoformat()
    subjects = StudentModelRepository._empty_subject_profiles()
    for subject, profile in subjects.items():
        profile["level"] = {
            "state": "proficient" if subject == "math" else "developing",
            "confidence": "high" if subject == "math" else "medium",
            "evidence_summary": "v0.2 分层教学测试预设，不代表真实测评结果。",
            "evidence_ids": ["seed_v02_upper_middle_profile"],
            "updated_at": now,
        }
    subjects["math"]["strengths"] = [
        "代数推理",
        "抓取关键条件",
        "快速进入核心建模",
    ]
    subjects["math"]["knowledge_graph"] = {
        "nodes": [
            {
                "concept_id": "algebraic_transformation",
                "name": "代数变形",
                "mastery": "mastered",
                "evidence_summary": "测试预设：能熟练进行常见代数变形。",
                "evidence_ids": ["seed_v02_math_profile"],
                "prerequisite_ids": [],
                "updated_at": now,
            },
            {
                "concept_id": "equation_setup",
                "name": "方程建模",
                "mastery": "proficient",
                "evidence_summary": "测试预设：能够根据条件建立方程关系。",
                "evidence_ids": ["seed_v02_math_profile"],
                "prerequisite_ids": ["algebraic_transformation"],
                "updated_at": now,
            },
            {
                "concept_id": "function_monotonicity",
                "name": "函数单调性",
                "mastery": "proficient",
                "evidence_summary": "测试预设：能够使用单调性分析常见函数。",
                "evidence_ids": ["seed_v02_math_profile"],
                "prerequisite_ids": ["algebraic_transformation"],
                "updated_at": now,
            },
        ],
        "edges": [
            {
                "source_concept_id": "algebraic_transformation",
                "target_concept_id": "equation_setup",
                "relation": "prerequisite",
            },
            {
                "source_concept_id": "algebraic_transformation",
                "target_concept_id": "function_monotonicity",
                "relation": "prerequisite",
            },
        ],
    }
    return {
        "student_id": student_id,
        "schema_version": 3,
        "model_version": 1,
        "updated_at": now,
        "identity": {
            "display_name": "v0.2 测试学生",
            "grade": "high_school_1",
            "class_name": "测试班",
            "school_name": None,
            "student_number": None,
            "age": 16,
            "region": None,
            "phone_number": None,
            "email_address": None,
        },
        "learning_profile": {
            "strength_subjects": ["math"],
            "support_subjects": [],
            "learning_styles": ["reading_writing", "practice_driven"],
            "learning_engagement": "high",
            "preferences": {
                "explanation_styles": ["rigorous", "concise", "key_point_first"],
                "preferred_pace": "fast",
                "interaction_style": "balanced",
                "challenge_preference": "challenging",
                "notes": "偏爱专业、准确、直击关键矛盾的讲解；减少铺垫和重复鼓励。",
            },
        },
        "subjects": subjects,
        "learning_history": {
            "persistent_misconceptions": [],
            "recent_attempts": [],
        },
        "academic_records": {
            "score_history": [],
            "latest_import_id": None,
            "latest_imported_at": None,
        },
        "education_goals": {
            "gaokao": {
                "exam_year": None,
                "target_total_score": None,
                "target_subject_scores": {},
                "notes": "",
            },
            "target_institutions": [],
        },
        "meta_knowledge_cards": [],
        "extensions": {
            "fixture": {
                "profile": "upper_middle_math_preferred",
                "synthetic": True,
            }
        },
    }


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    parser = argparse.ArgumentParser(description="创建 StudentModel v3 测试实例。")
    parser.add_argument("--student-id", default="v02_test_student")
    parser.add_argument(
        "--database",
        default=os.getenv("SESSION_DB_PATH", "data/sessions.db"),
    )
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    database = Path(args.database)
    if not database.is_absolute():
        database = PROJECT_ROOT / database
    repository = StudentModelRepository(database)
    if repository.get(args.student_id) is not None and not args.overwrite:
        raise SystemExit(
            f"StudentModel {args.student_id!r} already exists; use --overwrite to replace it."
        )
    repository.save(
        build_test_student(args.student_id),
        change_source="test_fixture",
    )
    print(f"Created StudentModel {args.student_id!r} in {database}.")


if __name__ == "__main__":
    main()
