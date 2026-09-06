"""持久化并以受控增量更新长期 StudentModel。"""

import json
import sqlite3
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from susu_agent.schemas.students import validate_student_model
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
                        model_version INTEGER NOT NULL,
                        model_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

    def get(self, student_id: str) -> dict[str, Any] | None:
        with closing(sqlite3.connect(self._db_path)) as connection:
            row = connection.execute(
                "SELECT model_json FROM student_models WHERE student_id = ?",
                (student_id,),
            ).fetchone()
        if row is None:
            return None
        model = json.loads(row[0])
        validate_student_model(model)
        return model

    def get_or_create(self, student_id: str, grade: str = "unknown") -> dict[str, Any]:
        model = self.get(student_id)
        if model is not None:
            return model
        now = datetime.now(timezone.utc).isoformat()
        model = {
            "student_id": student_id,
            "schema_version": 2,
            "model_version": 1,
            "updated_at": now,
            "grade": grade,
            "learning_history": {
                "concept_mastery": [],
                "persistent_misconceptions": [],
                "recent_attempts": [],
            },
            "meta_knowledge_cards": [],
        }
        self.save(model)
        return model

    def save(self, student_model: Mapping[str, Any]) -> None:
        model = deepcopy(dict(student_model))
        validate_student_model(model)
        with closing(sqlite3.connect(self._db_path)) as connection:
            with connection:
                connection.execute(
                    """
                    INSERT INTO student_models(student_id, model_version, model_json, updated_at)
                    VALUES(?, ?, ?, ?)
                    ON CONFLICT(student_id) DO UPDATE SET
                        model_version = excluded.model_version,
                        model_json = excluded.model_json,
                        updated_at = excluded.updated_at
                    """,
                    (
                        model["student_id"],
                        model.get("model_version", 1),
                        json.dumps(model, ensure_ascii=False),
                        model["updated_at"],
                    ),
                )

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
        history = current.setdefault("learning_history", {})
        mastery = history.setdefault("concept_mastery", [])
        by_concept = {item["concept_id"]: item for item in mastery}
        for update in patch.concept_updates:
            if update.confidence == "low" or not update.evidence_ids:
                continue
            value = {
                "concept_id": update.concept_id,
                "subject": update.subject,
                "mastery": update.proposed_mastery,
                "evidence_summary": update.evidence_summary,
                "updated_at": now,
            }
            if update.concept_id in by_concept:
                by_concept[update.concept_id].update(value)
            elif len(mastery) < 50:
                mastery.append(value)
                by_concept[update.concept_id] = value

        misconceptions = history.setdefault("persistent_misconceptions", [])
        by_misconception = {item["concept_id"]: item for item in misconceptions}
        for update in patch.misconception_updates:
            if update.confidence == "low" or not update.evidence_ids:
                continue
            existing = by_misconception.get(update.concept_id)
            if existing is not None:
                existing["description"] = update.description
                existing["occurrences"] += 1
                existing["last_seen_at"] = now
            elif len(misconceptions) < 20:
                value = {
                    "concept_id": update.concept_id,
                    "description": update.description,
                    "occurrences": 1,
                    "last_seen_at": now,
                }
                misconceptions.append(value)
                by_misconception[update.concept_id] = value

        cards = current.setdefault("meta_knowledge_cards", [])
        by_card = {item["card_id"]: item for item in cards}
        for update in patch.meta_knowledge_cards_to_add:
            value = {**update.model_dump(mode="json"), "updated_at": now}
            if update.card_id in by_card:
                by_card[update.card_id].update(value)
            elif len(cards) < 100:
                cards.append(value)
                by_card[update.card_id] = value

        current["model_version"] = current_version + 1
        current["updated_at"] = now
        validate_student_model(current)
        self.save(current)
        return current
