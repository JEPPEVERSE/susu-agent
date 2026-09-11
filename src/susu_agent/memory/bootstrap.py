"""把教案权威内容投影为可检索、可重建的 lesson chunks。"""

from datetime import datetime, timezone

from susu_agent.lesson_plan_loader import LessonPlanBundle
from susu_agent.memory.repositories import MemoryRepository
from susu_agent.schemas.memory import (
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    Provenance,
)


def index_lesson_plan(
    repository: MemoryRepository, lesson_plan: LessonPlanBundle
) -> int:
    """幂等同步教案章节；内容摘要变化时生成下一版本。"""
    count = 0
    current_ids: set[str] = set()
    for heading, (source, content) in lesson_plan.context_sections.items():
        step_ids = [
            step.step_id for step in lesson_plan.steps if heading in step.context_headings
        ]
        memory_id = f"lesson:{lesson_plan.subject}:{_slug(heading)}"
        current_ids.add(memory_id)
        current = repository.get(memory_id)
        if current is not None and current.metadata.get("content_digest") == lesson_plan.content_digest:
            continue
        now = datetime.now(timezone.utc)
        item = MemoryItem(
            memory_id=memory_id,
            memory_type=MemoryType.LESSON_CHUNK,
            canonical_text=content,
            retrieval_text=f"{heading}\n{content}",
            subject=lesson_plan.subject,
            task_stages=["solve", "verify_solution", "plan_instruction"],
            target_agents=["solution_agent", "solution_verifier", "teaching_planner"],
            lesson_plan_step_ids=step_ids,
            scope=MemoryScope.SUBJECT,
            provenance=Provenance(source_type="lesson_plan", source_id=source),
            confidence=1.0,
            version=(current.version + 1 if current else 1),
            status=MemoryStatus.ACTIVE,
            metadata={
                "heading": heading,
                "content_digest": lesson_plan.content_digest,
                "lesson_plan_version": lesson_plan.lesson_plan_version,
            },
            created_at=current.created_at if current else now,
            updated_at=now,
        )
        repository.save(
            item,
            change_source="lesson_plan_sync",
            expected_version=current.version if current else None,
        )
        count += 1
    for stale in repository.list_items(statuses=[MemoryStatus.ACTIVE]):
        if (
            stale.subject == lesson_plan.subject
            and stale.memory_type == MemoryType.LESSON_CHUNK
            and stale.provenance.source_type == "lesson_plan"
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
                change_source="lesson_plan_sync_removed",
                expected_version=stale.version,
            )
            count += 1
    return count


def _slug(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
