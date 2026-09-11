import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.memory.coordinator import CrossDomainCoordinator
from susu_agent.lesson_plan_loader import load_lesson_plan
from susu_agent.memory.bootstrap import index_lesson_plan
from susu_agent.memory.card_catalog import index_memory_cards
from susu_agent.memory.evaluator import RetrievalEvaluator
from susu_agent.memory.repositories import MemoryRepository
from susu_agent.memory.router import MemoryRouter
from susu_agent.memory.write_gate import MemoryWriteGate
from susu_agent.schemas.memory import (
    MemoryItem,
    MemoryScope,
    MemoryStatus,
    MemoryType,
    MemoryUpdateProposal,
    Provenance,
    RetrievalQuery,
)


def memory_item(
    memory_id: str,
    text: str,
    *,
    memory_type: MemoryType = MemoryType.QUESTION_CARD,
    agent: str = "teaching_planner",
    scope: MemoryScope = MemoryScope.SUBJECT,
    student_id: str | None = None,
    concepts: list[str] | None = None,
    status: MemoryStatus = MemoryStatus.ACTIVE,
    version: int = 1,
    metadata: dict | None = None,
) -> MemoryItem:
    now = datetime.now(timezone.utc)
    item_metadata = dict(metadata or {})
    if memory_type == MemoryType.QUESTION_CARD:
        applicability = item_metadata.pop("applicability", {})
        item_metadata["card"] = {
            "question_card_id": memory_id,
            "question_template": text,
            "teaching_goal": "测试教学目标",
            "expected_answer": "测试预期回答",
            "answer_checkpoints": ["测试检查点"],
            "applicability": applicability,
            "retrieval_text": text,
        }
    elif memory_type == MemoryType.MISCONCEPTION_CARD:
        applicability = item_metadata.pop("applicability", {})
        item_metadata["card"] = {
            "misconception_card_id": memory_id,
            "description": text,
            "diagnostic_signals": [text],
            "correction_strategy": "根据当前检查点进行纠正",
            "applicability": applicability,
            "retrieval_text": text,
        }
    return MemoryItem(
        memory_id=memory_id,
        memory_type=memory_type,
        canonical_text=text,
        retrieval_text=text,
        subject="math",
        task_stages=["plan_instruction", "assess_student_answer"],
        target_agents=[agent],
        concept_ids=concepts or [],
        scope=scope,
        student_id=student_id,
        provenance=Provenance(source_type="test", source_id=memory_id),
        confidence=0.8,
        status=status,
        version=version,
        metadata=item_metadata,
        created_at=now,
        updated_at=now,
    )


class V03MemoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.repository = MemoryRepository(Path(self.temp.name) / "memory.db")
        self.router = MemoryRouter(self.repository)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_collection_agent_subject_and_student_scope_are_hard_filters(self) -> None:
        self.repository.save(memory_item("question:freeze", "冻结变量", concepts=["freeze_variable"]))
        self.repository.save(
            memory_item(
                "misconception:private",
                "把二元函数当成一元函数直接求导",
                memory_type=MemoryType.MISCONCEPTION_CARD,
                agent="teaching_executor",
                scope=MemoryScope.STUDENT,
                student_id="student_a",
            )
        )
        wrong_student = RetrievalQuery(
            subject="math",
            task_stage="assess_student_answer",
            target_agent="teaching_executor",
            query_text="直接求导",
            memory_types=[MemoryType.MISCONCEPTION_CARD],
            student_id="student_b",
        )
        right_student = wrong_student.model_copy(update={"student_id": "student_a"})

        self.assertEqual(self.router.retrieve(wrong_student), [])
        self.assertEqual(
            [item.memory_id for item in self.router.retrieve(right_student)],
            ["misconception:private"],
        )

    def test_hybrid_ranking_tracks_source_and_prefers_matching_concept(self) -> None:
        self.repository.save(memory_item("question:vector", "向量投影和点积", concepts=["vector_projection"]))
        self.repository.save(memory_item("question:freeze", "多自由度时冻结一个变量", concepts=["freeze_variable"]))
        query = RetrievalQuery(
            subject="math",
            task_stage="plan_instruction",
            target_agent="teaching_planner",
            query_text="多个自由度怎样冻结变量",
            concept_ids=["freeze_variable"],
            memory_types=[MemoryType.QUESTION_CARD],
        )

        result = self.router.retrieve(query)

        self.assertEqual(result[0].memory_id, "question:freeze")
        self.assertIn("concept_ids", result[0].matched_features)
        self.assertEqual(result[0].source, "test:question:freeze")

    def test_card_applicability_is_checked_before_ranking(self) -> None:
        item = memory_item(
            "question:two-vars",
            "冻结变量",
            metadata={
                "applicability": {
                    "degrees_of_freedom_min": 2,
                    "goal_types": ["extremum"],
                }
            },
        )
        self.repository.save(item)
        query = RetrievalQuery(
            subject="math",
            task_stage="plan_instruction",
            target_agent="teaching_planner",
            query_text="冻结变量",
            memory_types=[MemoryType.QUESTION_CARD],
            goal_type="extremum",
            structural_features={"degrees_of_freedom": 1},
        )

        self.assertEqual(self.router.retrieve(query), [])
        eligible = query.model_copy(update={"structural_features": {"degrees_of_freedom": 2}})
        self.assertEqual(len(self.router.retrieve(eligible)), 1)

    def test_task_stage_is_a_hard_filter(self) -> None:
        self.repository.save(
            memory_item(
                "question:planning-only",
                "只用于教学规划",
                metadata={"applicability": {"task_stages": ["plan_instruction"]}},
            )
        )
        query = RetrievalQuery(
            subject="math",
            task_stage="assess_student_answer",
            target_agent="teaching_planner",
            query_text="教学规划",
            memory_types=[MemoryType.QUESTION_CARD],
        )

        self.assertEqual(self.router.retrieve(query), [])

    def test_catalog_sync_supersedes_removed_managed_items(self) -> None:
        plan = load_lesson_plan("math")
        now = datetime.now(timezone.utc)
        stale_lesson = MemoryItem(
            memory_id="lesson:math:removed",
            memory_type=MemoryType.LESSON_CHUNK,
            canonical_text="已经从教案删除的章节",
            retrieval_text="已经从教案删除的章节",
            subject="math",
            task_stages=["solve"],
            target_agents=["solution_agent"],
            scope=MemoryScope.SUBJECT,
            provenance=Provenance(source_type="lesson_plan", source_id="removed.md"),
            confidence=1.0,
            status=MemoryStatus.ACTIVE,
            created_at=now,
            updated_at=now,
        )
        stale_card = memory_item("question:removed", "已经删除的问题卡").model_copy(
            update={
                "provenance": Provenance(
                    source_type="lesson_plan_card_catalog",
                    source_id="lesson_plans/math/memory_cards.json",
                )
            }
        )
        self.repository.save(stale_lesson)
        self.repository.save(stale_card)

        index_lesson_plan(self.repository, plan)
        index_memory_cards(self.repository, plan)

        self.assertEqual(
            self.repository.get(stale_lesson.memory_id).status,
            MemoryStatus.SUPERSEDED,
        )
        self.assertEqual(
            self.repository.get(stale_card.memory_id).status,
            MemoryStatus.SUPERSEDED,
        )
        self.assertNotIn(stale_lesson.memory_id, self.repository.indexed_ids())
        self.assertNotIn(stale_card.memory_id, self.repository.indexed_ids())
        self.assertIn("question_freeze_variable", self.repository.indexed_ids())
        self.assertIn(
            "misconception_direct_derivative_multivariable",
            self.repository.indexed_ids(),
        )

    def test_unreviewed_proposal_is_not_indexed_and_approved_proposal_is(self) -> None:
        gate = MemoryWriteGate(self.repository)
        candidate = memory_item(
            "case:one",
            "学生通过冻结变量理解了二元最值",
            memory_type=MemoryType.TEACHING_CASE,
            status=MemoryStatus.ACTIVE,
        )
        proposal = MemoryUpdateProposal(
            proposal_id="proposal:one",
            operation="add",
            candidate_content=candidate,
            supporting_evidence_ids=["session:a", "session:b"],
            evidence_source_ids=["session:a", "session:b"],
            proposed_confidence=0.7,
            scope=MemoryScope.SUBJECT,
            required_reviewers=["math", "pedagogy", "privacy", "duplicate_conflict"],
        )

        gate.submit(proposal)
        self.assertNotIn("case:one", self.repository.indexed_ids())
        gate.apply(proposal, {"math": True, "pedagogy": True})
        self.assertIn("case:one", self.repository.indexed_ids())

    def test_global_write_requires_multiple_independent_evidence(self) -> None:
        gate = MemoryWriteGate(self.repository)
        proposal = MemoryUpdateProposal(
            proposal_id="proposal:weak",
            operation="add",
            candidate_content=memory_item("case:weak", "一次教学看起来有效"),
            supporting_evidence_ids=["session:a"],
            evidence_source_ids=["session:a"],
            proposed_confidence=0.3,
            scope=MemoryScope.SUBJECT,
            required_reviewers=["math", "pedagogy", "privacy", "duplicate_conflict"],
        )

        approved, reviews = gate.review(proposal, {"math": True, "pedagogy": True})

        self.assertFalse(approved)
        self.assertFalse(reviews["evidence"])
        self.assertNotIn("case:weak", self.repository.indexed_ids())

    def test_shared_candidate_cannot_embed_session_identifier(self) -> None:
        gate = MemoryWriteGate(self.repository)
        proposal = MemoryUpdateProposal(
            proposal_id="proposal:privacy",
            operation="add",
            candidate_content=memory_item(
                "case:privacy",
                "session:a 的学生通过冻结变量理解了题目",
                memory_type=MemoryType.TEACHING_CASE,
            ),
            supporting_evidence_ids=["evidence:a", "evidence:b"],
            evidence_source_ids=["session:a", "session:b"],
            proposed_confidence=0.7,
            scope=MemoryScope.SUBJECT,
            required_reviewers=["math", "pedagogy", "privacy", "duplicate_conflict"],
        )

        approved, reviews = gate.review(
            proposal, {"math": True, "pedagogy": True}
        )

        self.assertFalse(approved)
        self.assertFalse(reviews["privacy"])

    def test_rollback_restores_content_and_active_index(self) -> None:
        first = memory_item(
            "case:versioned",
            "第一版",
            version=1,
            memory_type=MemoryType.TEACHING_CASE,
        )
        self.repository.save(first)
        second = first.model_copy(
            update={"version": 2, "canonical_text": "第二版", "retrieval_text": "第二版"}
        )
        self.repository.save(second, expected_version=1)

        restored = self.repository.rollback("case:versioned", 1)

        self.assertEqual(restored.version, 3)
        self.assertEqual(restored.canonical_text, "第一版")
        self.assertIn(restored.memory_id, self.repository.indexed_ids())

    def test_failure_classification_and_progressive_concept_expansion(self) -> None:
        self.repository.save(
            memory_item(
                "graph:math",
                "自由度可由冻结变量降低",
                memory_type=MemoryType.CONCEPT_GRAPH,
                agent="memory_router",
                metadata={
                    "edges": [
                        {
                            "source": "degrees_of_freedom",
                            "relation": "can_be_reduced_by",
                            "target": "freeze_variable",
                        }
                    ]
                },
            )
        )
        self.repository.save(
            memory_item(
                "question:expanded",
                "先冻结一个变量",
                concepts=["freeze_variable"],
            )
        )
        query = RetrievalQuery(
            subject="math",
            task_stage="plan_instruction",
            target_agent="teaching_planner",
            query_text="降低自由度",
            concept_ids=["degrees_of_freedom"],
            memory_types=[MemoryType.QUESTION_CARD],
        )
        coordinator = CrossDomainCoordinator(
            self.router, RetrievalEvaluator(relevance_threshold=0.01)
        )

        result = coordinator.retrieve(query)

        self.assertIsNone(result.failure_type)
        self.assertEqual(result.expansion_level, 1)
        self.assertEqual(result.evidence[0].memory_id, "question:expanded")


if __name__ == "__main__":
    unittest.main()
