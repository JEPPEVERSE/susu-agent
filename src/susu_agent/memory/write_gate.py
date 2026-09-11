"""长期记忆更新的确定性审核、发布、隔离与回滚门。"""

import json
from datetime import datetime, timezone
from typing import Mapping

from susu_agent.memory.lexical_retriever import tokenize
from susu_agent.memory.repositories import MemoryRepository
from susu_agent.schemas.memory import (
    MemoryItem,
    MemoryOperation,
    MemoryScope,
    MemoryStatus,
    MemoryUpdateProposal,
)


class MemoryWriteGate:
    def __init__(self, repository: MemoryRepository) -> None:
        self.repository = repository

    def submit(self, proposal: MemoryUpdateProposal) -> MemoryUpdateProposal:
        """只保存提案；不把候选内容放入正式索引。"""
        candidate = proposal.candidate_content
        if candidate is not None and candidate.status == MemoryStatus.ACTIVE:
            candidate = candidate.model_copy(update={"status": MemoryStatus.STAGING})
            proposal = proposal.model_copy(update={"candidate_content": candidate})
        self.repository.save_proposal(proposal)
        self.repository.record_event(
            "proposal_submitted", {}, proposal_id=proposal.proposal_id
        )
        return proposal

    def review(
        self,
        proposal: MemoryUpdateProposal,
        reviewer_decisions: Mapping[str, bool] | None = None,
    ) -> tuple[bool, dict[str, object]]:
        decisions = dict(reviewer_decisions or {})
        reviews: dict[str, object] = {
            "privacy": self._privacy_check(proposal),
            "duplicate_conflict": self._duplicate_conflict_check(proposal),
            "version": self._version_check(proposal),
            "evidence": self._evidence_check(proposal),
        }
        for reviewer in proposal.required_reviewers:
            if reviewer in {"privacy", "duplicate_conflict"}:
                continue
            reviews[reviewer] = bool(decisions.get(reviewer, False))
        approved = all(bool(value) for value in reviews.values()) and not proposal.risk_flags
        reviewed = proposal.model_copy(update={"status": "approved" if approved else "rejected"})
        self.repository.save_proposal(reviewed, reviews)
        self.repository.record_event(
            "proposal_reviewed",
            {"approved": approved, "reviews": reviews},
            proposal_id=proposal.proposal_id,
        )
        return approved, reviews

    def apply(
        self,
        proposal: MemoryUpdateProposal,
        reviewer_decisions: Mapping[str, bool] | None = None,
    ) -> MemoryItem:
        approved, reviews = self.review(proposal, reviewer_decisions)
        if not approved:
            raise ValueError(f"Memory proposal did not pass review: {reviews}")
        operation = proposal.operation
        if operation == MemoryOperation.ADD:
            candidate = proposal.candidate_content
            if candidate is None:
                raise ValueError("Add proposal has no candidate content.")
            active = candidate.model_copy(
                update={"status": MemoryStatus.ACTIVE, "updated_at": datetime.now(timezone.utc)}
            )
            result = self.repository.save(active, change_source=proposal.proposal_id)
        else:
            current = self.repository.get(proposal.target_memory_id or "")
            if current is None:
                raise ValueError("Target memory does not exist.")
            if operation == MemoryOperation.ROLLBACK:
                rollback_version = proposal.rollback_version
                if rollback_version is None:
                    raise ValueError("Rollback proposal has no rollback_version.")
                result = self.repository.rollback(current.memory_id, rollback_version)
            elif operation == MemoryOperation.SUPERSEDE:
                candidate = proposal.candidate_content
                if candidate is None:
                    raise ValueError("Supersede proposal has no candidate content.")
                if candidate.memory_id == current.memory_id:
                    replacement = candidate.model_copy(
                        update={
                            "version": current.version + 1,
                            "status": MemoryStatus.ACTIVE,
                            "created_at": current.created_at,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    )
                    result = self.repository.save(
                        replacement,
                        change_source=proposal.proposal_id,
                        expected_version=current.version,
                    )
                else:
                    superseded = current.model_copy(
                        update={
                            "version": current.version + 1,
                            "status": MemoryStatus.SUPERSEDED,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    )
                    self.repository.save(
                        superseded,
                        change_source=proposal.proposal_id,
                        expected_version=current.version,
                    )
                    replacement = candidate.model_copy(
                        update={
                            "status": MemoryStatus.ACTIVE,
                            "updated_at": datetime.now(timezone.utc),
                        }
                    )
                    result = self.repository.save(
                        replacement, change_source=proposal.proposal_id
                    )
            else:
                result = self._apply_update(current, proposal)
                result = self.repository.save(
                    result,
                    change_source=proposal.proposal_id,
                    expected_version=current.version,
                )
        applied = proposal.model_copy(update={"status": "applied"})
        self.repository.save_proposal(applied, reviews)
        return result

    @staticmethod
    def _apply_update(
        current: MemoryItem, proposal: MemoryUpdateProposal
    ) -> MemoryItem:
        operation = proposal.operation
        changes: dict[str, object] = {
            "version": current.version + 1,
            "updated_at": datetime.now(timezone.utc),
        }
        if operation == MemoryOperation.REINFORCE:
            changes["confidence"] = min(1.0, max(current.confidence, proposal.proposed_confidence))
        elif operation == MemoryOperation.WEAKEN:
            changes["confidence"] = min(current.confidence, proposal.proposed_confidence)
        elif operation == MemoryOperation.QUARANTINE:
            changes["status"] = MemoryStatus.QUARANTINED
        elif operation == MemoryOperation.EXPIRE:
            changes["status"] = MemoryStatus.EXPIRED
        elif operation == MemoryOperation.SUPERSEDE:
            changes["status"] = MemoryStatus.SUPERSEDED
        elif operation == MemoryOperation.MERGE:
            if proposal.candidate_content is None:
                raise ValueError("Merge requires candidate content.")
            candidate = proposal.candidate_content
            changes.update(
                memory_type=candidate.memory_type,
                canonical_text=candidate.canonical_text,
                retrieval_text=candidate.retrieval_text,
                task_stages=candidate.task_stages,
                target_agents=candidate.target_agents,
                concept_ids=candidate.concept_ids,
                lesson_plan_step_ids=candidate.lesson_plan_step_ids,
                provenance=candidate.provenance,
                confidence=proposal.proposed_confidence,
                embedding_model=candidate.embedding_model,
                metadata=candidate.metadata,
                status=MemoryStatus.ACTIVE,
            )
        else:
            raise ValueError(f"Unsupported update operation: {operation.value}")
        return current.model_copy(update=changes)

    def _duplicate_conflict_check(self, proposal: MemoryUpdateProposal) -> bool:
        candidate = proposal.candidate_content
        if candidate is None or proposal.operation not in {
            MemoryOperation.ADD,
            MemoryOperation.MERGE,
            MemoryOperation.SUPERSEDE,
        }:
            return True
        candidate_terms = set(tokenize(candidate.canonical_text))
        for item in self.repository.list_items(statuses=[MemoryStatus.ACTIVE]):
            if item.memory_id in {
                candidate.memory_id,
                proposal.target_memory_id,
            }:
                if proposal.operation == MemoryOperation.ADD:
                    return False
                continue
            if item.subject != candidate.subject or item.memory_type != candidate.memory_type:
                continue
            item_terms = set(tokenize(item.canonical_text))
            union = candidate_terms | item_terms
            similarity = len(candidate_terms & item_terms) / len(union) if union else 1.0
            if similarity >= 0.92:
                return False
        return True

    def _version_check(self, proposal: MemoryUpdateProposal) -> bool:
        if proposal.operation == MemoryOperation.ADD:
            candidate = proposal.candidate_content
            return candidate is not None and self.repository.get(candidate.memory_id) is None
        target = self.repository.get(proposal.target_memory_id or "")
        target_exists = target is not None
        if target is not None and target.scope != proposal.scope:
            return False
        candidate = proposal.candidate_content
        if target is not None and candidate is not None and (
            candidate.subject != target.subject or candidate.scope != target.scope
        ):
            return False
        if (
            proposal.operation == MemoryOperation.SUPERSEDE
            and candidate is not None
            and candidate.memory_id != proposal.target_memory_id
            and self.repository.get(candidate.memory_id) is not None
        ):
            return False
        return target_exists

    @staticmethod
    def _privacy_check(proposal: MemoryUpdateProposal) -> bool:
        candidate = proposal.candidate_content
        if proposal.scope == MemoryScope.STUDENT:
            return candidate is None or bool(candidate.student_id)
        if proposal.scope in {MemoryScope.GLOBAL, MemoryScope.SUBJECT}:
            if candidate is None:
                return True
            if candidate.student_id is not None or candidate.session_id is not None:
                return False
            shared_text = "\n".join(
                (
                    candidate.canonical_text,
                    candidate.retrieval_text,
                    json.dumps(candidate.metadata, ensure_ascii=False),
                )
            )
            return not any(
                source_id and source_id in shared_text
                for source_id in proposal.evidence_source_ids
            )
        return True

    @staticmethod
    def _evidence_check(proposal: MemoryUpdateProposal) -> bool:
        if proposal.operation in {
            MemoryOperation.QUARANTINE,
            MemoryOperation.EXPIRE,
            MemoryOperation.ROLLBACK,
        }:
            return True
        unique_evidence = set(proposal.supporting_evidence_ids)
        if proposal.scope in {MemoryScope.GLOBAL, MemoryScope.SUBJECT}:
            return len(unique_evidence) >= 2 and len(set(proposal.evidence_source_ids)) >= 2
        return len(unique_evidence) >= 1
