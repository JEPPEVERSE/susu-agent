"""从教案目录加载并索引经过人工维护的 v0.3 Card。"""

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from susu_agent.lesson_plan_loader import DEFAULT_LESSON_PLANS_DIRECTORY, LessonPlanBundle
from susu_agent.memory.repositories import MemoryRepository
from susu_agent.schemas.memory import (
    MemoryItem,
    MemoryCardCatalog,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MisconceptionCard,
    Provenance,
    QuestionCard,
)


def index_memory_cards(
    repository: MemoryRepository,
    lesson_plan: LessonPlanBundle,
    *,
    lesson_plans_directory: Path = DEFAULT_LESSON_PLANS_DIRECTORY,
) -> int:
    path = lesson_plans_directory / lesson_plan.subject / "memory_cards.json"
    if not path.is_file():
        return 0
    catalog = MemoryCardCatalog.model_validate_json(path.read_text(encoding="utf-8"))
    if catalog.subject != lesson_plan.subject:
        raise ValueError("Memory card catalog metadata does not match lesson plan.")
    known_steps = set(lesson_plan.step_ids)
    catalog_digest = sha256(path.read_bytes()).hexdigest()
    cards: list[tuple[MemoryType, QuestionCard | MisconceptionCard]] = []
    cards.extend(
        (MemoryType.QUESTION_CARD, value)
        for value in catalog.question_cards
    )
    cards.extend(
        (MemoryType.MISCONCEPTION_CARD, value)
        for value in catalog.misconception_cards
    )
    count = 0
    current_ids: set[str] = set()
    for memory_type, card in cards:
        applicability = card.applicability
        unknown_steps = set(applicability.lesson_plan_step_ids) - known_steps
        if unknown_steps:
            raise ValueError(f"Memory Card references unknown lesson steps: {sorted(unknown_steps)!r}")
        memory_id = (
            card.question_card_id
            if isinstance(card, QuestionCard)
            else card.misconception_card_id
        )
        current_ids.add(memory_id)
        current = repository.get(memory_id)
        if current is not None and current.metadata.get("catalog_digest") == catalog_digest:
            continue
        now = datetime.now(timezone.utc)
        canonical_text = json.dumps(card.model_dump(mode="json"), ensure_ascii=False)
        item = MemoryItem(
            memory_id=memory_id,
            memory_type=memory_type,
            canonical_text=canonical_text,
            retrieval_text=card.retrieval_text,
            subject=lesson_plan.subject,
            task_stages=(
                applicability.task_stages
                or (["plan_instruction"] if memory_type == MemoryType.QUESTION_CARD else ["assess_student_answer"])
            ),
            target_agents=(
                ["teaching_planner"]
                if memory_type == MemoryType.QUESTION_CARD
                else ["teaching_executor", "student_model_summarizer"]
            ),
            concept_ids=applicability.concept_ids,
            lesson_plan_step_ids=applicability.lesson_plan_step_ids,
            scope=MemoryScope.SUBJECT,
            provenance=Provenance(
                source_type="lesson_plan_card_catalog",
                source_id=str(path.relative_to(lesson_plans_directory.parent)).replace("\\", "/"),
                created_by="teacher",
            ),
            confidence=1.0,
            version=current.version + 1 if current else 1,
            status=MemoryStatus.ACTIVE,
            metadata={
                "card": card.model_dump(mode="json"),
                "catalog_digest": catalog_digest,
                "lesson_plan_version": lesson_plan.lesson_plan_version,
            },
            created_at=current.created_at if current else now,
            updated_at=now,
        )
        repository.save(
            item,
            change_source="lesson_plan_card_sync",
            expected_version=current.version if current else None,
        )
        count += 1
    for stale in repository.list_items(statuses=[MemoryStatus.ACTIVE]):
        if (
            stale.subject == lesson_plan.subject
            and stale.memory_type
            in {MemoryType.QUESTION_CARD, MemoryType.MISCONCEPTION_CARD}
            and stale.provenance.source_type == "lesson_plan_card_catalog"
            and stale.memory_id not in current_ids
        ):
            repository.save(
                stale.model_copy(
                    update={
                        "version": stale.version + 1,
                        "status": MemoryStatus.SUPERSEDED,
                        "updated_at": datetime.now(timezone.utc),
                    }
                ),
                change_source="lesson_plan_card_sync_removed",
                expected_version=stale.version,
            )
            count += 1
    return count
