"""持久化并以受控增量更新长期 StudentModel。"""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from susu_agent.schemas.students import SUBJECTS, validate_student_model
from susu_agent.schemas.v02 import StudentModelPatch


class StudentModelRepository:
    def __init__(self, db_path: str | Path) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self._db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS student_models (
                        student_id TEXT PRIMARY KEY,
                        schema_version INTEGER NOT NULL DEFAULT 3,
                        model_version INTEGER NOT NULL,
                        model_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(student_models)"
                    ).fetchall()
                }
                if "schema_version" not in columns:
                    connection.execute(
                        "ALTER TABLE student_models ADD COLUMN "
                        "schema_version INTEGER NOT NULL DEFAULT 1"
                    )
                if "created_at" not in columns:
                    connection.execute(
                        "ALTER TABLE student_models ADD COLUMN created_at TEXT"
                    )
                    connection.execute(
                        "UPDATE student_models SET created_at = updated_at "
                        "WHERE created_at IS NULL"
                    )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS student_model_versions (
                        revision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        student_id TEXT NOT NULL,
                        schema_version INTEGER NOT NULL,
                        model_version INTEGER NOT NULL,
                        model_json TEXT NOT NULL,
                        change_source TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_student_models_updated_at "
                    "ON student_models(updated_at)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_student_model_versions_lookup "
                    "ON student_model_versions(student_id, model_version DESC)"
                )

    def get(self, student_id: str) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self._db_path)) as connection:
            row = connection.execute(
                "SELECT model_json FROM student_models WHERE student_id = ?",
                (student_id,),
            ).fetchone()
        if row is None:
            return None
        stored_model = json.loads(row[0])
        model = self._upgrade_model(stored_model)
        validate_student_model(model)
        if model != stored_model:
            self.save(model, change_source="schema_migration")
        return model

    def get_or_create(self, student_id: str, grade: str = "unknown") -> dict[str, Any]:
        model = self.get(student_id)
        if model is not None:
            return model
        now = datetime.now(timezone.utc).isoformat()
        model = {
            "student_id": student_id,
            "schema_version": 3,
            "model_version": 1,
            "updated_at": now,
            "identity": {
                "display_name": None,
                "grade": grade,
                "class_name": None,
                "school_name": None,
                "student_number": None,
                "age": None,
                "region": None,
                "phone_number": None,
                "email_address": None,
            },
            "learning_profile": {
                "strength_subjects": [],
                "support_subjects": [],
                "learning_styles": [],
                "learning_engagement": "unknown",
                "preferences": {
                    "explanation_styles": [],
                    "preferred_pace": "unknown",
                    "interaction_style": "unknown",
                    "challenge_preference": "unknown",
                    "notes": "",
                },
            },
            "subjects": self._empty_subject_profiles(),
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
            "extensions": {},
        }
        self.save(model, change_source="create")
        return model

    def save(
        self,
        student_model: Mapping[str, Any],
        *,
        change_source: str = "manual",
    ) -> None:
        """保存完整模型；适合人工配置和 Schema 迁移。"""
        model = deepcopy(dict(student_model))
        validate_student_model(model)
        self._save_model(model, change_source=change_source)

    def _save_model(
        self,
        model: Mapping[str, Any],
        *,
        change_source: str,
        expected_model_version: int | None = None,
    ) -> None:
        payload = json.dumps(model, ensure_ascii=False)
        with closing(sqlite3.connect(self._db_path)) as connection:
            connection.execute("PRAGMA busy_timeout = 5000")
            try:
                connection.execute("BEGIN IMMEDIATE")
                existing = connection.execute(
                    "SELECT model_version, created_at FROM student_models "
                    "WHERE student_id = ?",
                    (model["student_id"],),
                ).fetchone()
                if expected_model_version is not None:
                    if existing is None or existing[0] != expected_model_version:
                        raise ValueError("Student model version conflict.")
                    cursor = connection.execute(
                        """
                        UPDATE student_models
                        SET schema_version = ?, model_version = ?, model_json = ?,
                            updated_at = ?
                        WHERE student_id = ? AND model_version = ?
                        """,
                        (
                            model["schema_version"],
                            model["model_version"],
                            payload,
                            model["updated_at"],
                            model["student_id"],
                            expected_model_version,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise ValueError("Student model version conflict.")
                else:
                    created_at = (
                        existing[1]
                        if existing is not None and existing[1]
                        else model["updated_at"]
                    )
                    connection.execute(
                        """
                        INSERT INTO student_models(
                            student_id, schema_version, model_version, model_json,
                            created_at, updated_at
                        ) VALUES(?, ?, ?, ?, ?, ?)
                        ON CONFLICT(student_id) DO UPDATE SET
                            schema_version = excluded.schema_version,
                            model_version = excluded.model_version,
                            model_json = excluded.model_json,
                            updated_at = excluded.updated_at
                        """,
                        (
                            model["student_id"],
                            model["schema_version"],
                            model["model_version"],
                            payload,
                            created_at,
                            model["updated_at"],
                        ),
                    )
                connection.execute(
                    """
                    INSERT INTO student_model_versions(
                        student_id, schema_version, model_version, model_json,
                        change_source, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        model["student_id"],
                        model["schema_version"],
                        model["model_version"],
                        payload,
                        change_source,
                        model["updated_at"],
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def get_version_history(
        self, student_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        """返回最近的 StudentModel 快照元数据，不默认加载大型 JSON。"""
        bounded_limit = min(max(limit, 1), 100)
        with closing(sqlite3.connect(self._db_path)) as connection:
            rows = connection.execute(
                """
                SELECT revision_id, schema_version, model_version,
                       change_source, created_at
                FROM student_model_versions
                WHERE student_id = ?
                ORDER BY revision_id DESC
                LIMIT ?
                """,
                (student_id, bounded_limit),
            ).fetchall()
        return [
            {
                "revision_id": row[0],
                "schema_version": row[1],
                "model_version": row[2],
                "change_source": row[3],
                "created_at": row[4],
            }
            for row in rows
        ]

    def apply_patch(
        self,
        student_model: Mapping[str, Any],
        patch: StudentModelPatch,
    ) -> dict[str, Any]:
        """乐观锁校验后合并高/中置信度更新，低置信度只保留在短期证据中。"""
        current = deepcopy(dict(student_model))
        current_version = int(current.get("model_version", 1))
        if patch.base_model_version != current_version:
            raise ValueError("Student model version conflict.")
        now = datetime.now(timezone.utc).isoformat()
        subjects = current["subjects"]
        for update in patch.concept_updates:
            if update.confidence == "low" or not update.evidence_ids:
                continue
            mastery = subjects[update.subject]["knowledge_graph"]["nodes"]
            by_concept = {item["concept_id"]: item for item in mastery}
            value = {
                "concept_id": update.concept_id,
                "mastery": update.proposed_mastery,
                "evidence_summary": update.evidence_summary,
                "evidence_ids": update.evidence_ids,
                "updated_at": now,
            }
            if update.concept_id in by_concept:
                by_concept[update.concept_id].update(value)
            elif len(mastery) < 500:
                inserted = {**value, "name": None, "prerequisite_ids": []}
                mastery.append(inserted)
                by_concept[update.concept_id] = inserted

        history = current.setdefault("learning_history", {})
        misconceptions = history.setdefault("persistent_misconceptions", [])
        by_misconception = {
            (item["subject"], item["concept_id"]): item for item in misconceptions
        }
        for update in patch.misconception_updates:
            if update.confidence == "low" or not update.evidence_ids:
                continue
            key = (update.subject, update.concept_id)
            existing = by_misconception.get(key)
            if existing is not None:
                existing["description"] = update.description
                existing["occurrences"] += 1
                existing["last_seen_at"] = now
            elif len(misconceptions) < 100:
                value = {
                    "concept_id": update.concept_id,
                    "subject": update.subject,
                    "description": update.description,
                    "occurrences": 1,
                    "last_seen_at": now,
                }
                misconceptions.append(value)
                by_misconception[key] = value

        for update in patch.subject_level_updates:
            if update.confidence == "low" or not update.evidence_ids:
                continue
            level = subjects[update.subject]["level"]
            level["state"] = self.transition_subject_level(
                level["state"], update.proposed_state
            )
            level["confidence"] = update.confidence
            level["evidence_summary"] = update.evidence_summary
            level["evidence_ids"] = update.evidence_ids
            level["updated_at"] = now

        cards = current.setdefault("meta_knowledge_cards", [])
        by_card = {item["card_id"]: item for item in cards}
        for update in patch.meta_knowledge_cards_to_add:
            value = {**update.model_dump(mode="json"), "updated_at": now}
            if update.card_id in by_card:
                by_card[update.card_id].update(value)
            elif len(cards) < 200:
                cards.append(value)
                by_card[update.card_id] = value

        current["model_version"] = current_version + 1
        current["updated_at"] = now
        validate_student_model(current)
        self._save_model(
            current,
            change_source="summarizer_patch",
            expected_model_version=current_version,
        )
        return current

    @staticmethod
    def _empty_subject_profiles() -> dict[str, Any]:
        return {
            subject: {
                "level": {
                    "state": "unassessed",
                    "confidence": "low",
                    "evidence_summary": "",
                    "evidence_ids": [],
                    "updated_at": None,
                },
                "strengths": [],
                "weaknesses": [],
                "knowledge_graph": {"nodes": [], "edges": []},
                "notes": "",
            }
            for subject in SUBJECTS
        }

    @staticmethod
    def transition_subject_level(current: str, proposed: str) -> str:
        """执行学科水平有限状态转移；已有评级每次最多移动一级。"""
        states = ("unassessed", "foundation", "developing", "proficient", "advanced")
        if current not in states or proposed not in states:
            raise ValueError("Unknown subject level state.")
        if current == "unassessed" or current == proposed:
            return proposed
        if proposed == "unassessed":
            return current
        current_index = states.index(current)
        proposed_index = states.index(proposed)
        direction = 1 if proposed_index > current_index else -1
        return states[current_index + direction]

    @classmethod
    def _upgrade_model(cls, stored: Mapping[str, Any]) -> dict[str, Any]:
        model = deepcopy(dict(stored))
        schema_version = int(model.get("schema_version", 1))
        if schema_version == 3:
            return model
        if schema_version > 3:
            raise ValueError(f"Unsupported StudentModel schema_version: {schema_version}.")

        legacy_identity = model.get("identity", {})
        legacy_school = legacy_identity.get("school_name")
        if isinstance(legacy_school, Mapping):
            school_name = (
                legacy_school.get("senior_high")
                or legacy_school.get("junior_high")
                or legacy_school.get("college")
            )
        else:
            school_name = legacy_school
        identity = {
            "display_name": legacy_identity.get("name"),
            "grade": model.get("grade", "unknown"),
            "class_name": legacy_identity.get("class_name"),
            "school_name": school_name,
            "student_number": legacy_identity.get("student_number"),
            "age": legacy_identity.get("age"),
            "region": legacy_identity.get("region"),
            "phone_number": legacy_identity.get("phone_number"),
            "email_address": legacy_identity.get("email_address"),
        }

        capability = legacy_identity.get("capability_map", {})
        old_preferences = model.get("prefered_style", {})
        personality = model.get("personality", {})
        strength_subjects = [capability.get("good_at")] if capability.get("good_at") else []
        support_subjects = [capability.get("bad_at")] if capability.get("bad_at") else []
        subjects = cls._empty_subject_profiles()
        legacy_history = model.get("learning_history", {})
        concept_subjects: dict[str, str] = {}
        for item in legacy_history.get("concept_mastery", []):
            subject = item.get("subject")
            if subject not in SUBJECTS:
                continue
            concept_subjects[item["concept_id"]] = subject
            subjects[subject]["knowledge_graph"]["nodes"].append(
                {
                    "concept_id": item["concept_id"],
                    "name": None,
                    "mastery": item.get("mastery", "unknown"),
                    "evidence_summary": item.get("evidence_summary", ""),
                    "evidence_ids": [],
                    "prerequisite_ids": [],
                    "updated_at": item.get("updated_at"),
                }
            )
        misconceptions = []
        for item in legacy_history.get("persistent_misconceptions", []):
            misconceptions.append(
                {
                    **item,
                    "subject": item.get("subject")
                    or concept_subjects.get(item.get("concept_id"), "math"),
                }
            )

        recent_scores = model.get("score_map", {}).get("recent_scores", [])
        return {
            "student_id": model["student_id"],
            "schema_version": 3,
            "model_version": model.get("model_version", 1),
            "updated_at": model["updated_at"],
            "identity": identity,
            "learning_profile": {
                "strength_subjects": strength_subjects,
                "support_subjects": support_subjects,
                "learning_styles": [],
                "learning_engagement": personality.get("learning_engagement", "unknown"),
                "preferences": {
                    "explanation_styles": old_preferences.get("explanation_styles", []),
                    "preferred_pace": old_preferences.get("preferred_pace", "unknown"),
                    "interaction_style": personality.get("interaction_style", "unknown"),
                    "challenge_preference": "unknown",
                    "notes": old_preferences.get("notes", personality.get("notes", "")),
                },
            },
            "subjects": subjects,
            "learning_history": {
                "persistent_misconceptions": misconceptions,
                "recent_attempts": legacy_history.get("recent_attempts", []),
            },
            "academic_records": {
                "score_history": recent_scores,
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
            "meta_knowledge_cards": model.get("meta_knowledge_cards", []),
            "extensions": {},
        }
