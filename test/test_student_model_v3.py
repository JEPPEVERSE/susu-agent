import json
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.agents.teaching_planner import (
    build_subject_level_policy,
    build_teaching_planner_input,
)
from susu_agent.agents.teaching_executor import build_executor_student_context
from susu_agent.agents.student_model_updater import (
    build_student_model_summarizer_input,
)
from susu_agent.repositories.student_model_repository import StudentModelRepository
from susu_agent.orchestrator import V02Orchestrator
from susu_agent.schemas.solution import Solution, SolutionStep, TutorQuestion
from susu_agent.schemas.v02 import (
    StudentModelPatch,
    SubjectLevelPatch,
    TeachingStrategy,
    TeachingStrategyNode,
    TeachingTransition,
    VerificationReport,
)


def make_levelled_solution() -> Solution:
    return Solution(
        goal="完成题目",
        strategy_summary="分层提问。",
        steps=[
            SolutionStep(
                solution_step_id="step_0",
                lesson_plan_step_id="S1",
                title="基础审题",
                goal="识别目标",
                derivation="先识别题目目标。",
                result="目标明确。",
                tutor_questions=[
                    TutorQuestion(
                        question_id="question_0",
                        question="题目要求什么？",
                        difficulty="foundation",
                        teaching_goal="识别目标",
                        expected_answer="说出题目目标。",
                    )
                ],
            ),
            SolutionStep(
                solution_step_id="step_1",
                lesson_plan_step_id="S3",
                title="核心建模",
                goal="建立关系",
                derivation="建立变量关系。",
                result="得到关系式。",
                tutor_questions=[
                    TutorQuestion(
                        question_id="question_1",
                        question="如何建立核心关系？",
                        difficulty="advanced",
                        teaching_goal="完成建模",
                        expected_answer="写出核心关系式。",
                    )
                ],
            ),
        ],
        final_answer="测试答案",
    )


class StudentModelV3Tests(unittest.TestCase):
    def test_default_model_has_identity_and_six_subject_graphs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = StudentModelRepository(Path(temp_directory) / "state.db")
            model = repository.get_or_create("student_0", "high_school_2")

        self.assertEqual(model["schema_version"], 3)
        self.assertEqual(model["identity"]["grade"], "high_school_2")
        self.assertIsNone(model["identity"]["class_name"])
        self.assertEqual(
            set(model["subjects"]),
            {"math", "chinese", "english", "physics", "chemistry", "biology"},
        )
        self.assertEqual(
            model["subjects"]["math"]["level"]["state"], "unassessed"
        )
        self.assertEqual(
            model["subjects"]["biology"]["knowledge_graph"],
            {"nodes": [], "edges": []},
        )
        self.assertIn("score_history", model["academic_records"])
        self.assertIn("target_institutions", model["education_goals"])

    def test_executor_receives_only_current_subject_relevant_student_context(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = StudentModelRepository(Path(temp_directory) / "state.db")
            model = repository.get_or_create("student_0", "high_school_1")
        model["identity"].update(
            {
                "display_name": "测试学生",
                "class_name": "一班",
                "phone_number": "not-for-agent-context",
            }
        )
        model["learning_profile"]["preferences"]["explanation_styles"] = [
            "rigorous",
            "concise",
        ]
        model["subjects"]["math"]["knowledge_graph"]["nodes"] = [
            {
                "concept_id": "equation_setup",
                "name": "列方程",
                "mastery": "proficient",
                "evidence_summary": "已有证据",
                "evidence_ids": ["evidence_0"],
                "prerequisite_ids": [],
                "updated_at": None,
            },
            {
                "concept_id": "unrelated_concept",
                "name": "无关知识点",
                "mastery": "learning",
                "evidence_summary": "",
                "evidence_ids": [],
                "prerequisite_ids": [],
                "updated_at": None,
            },
        ]

        context = build_executor_student_context(
            model,
            {"lesson_plan": {"subject": "math"}},
            {"concept_ids": ["equation_setup"]},
        )

        self.assertEqual(context["identity"], {
            "display_name": "测试学生",
            "grade": "high_school_1",
        })
        self.assertNotIn("subjects", context)
        self.assertNotIn("phone_number", context["identity"])
        self.assertEqual(
            context["learning_profile"]["preferences"]["explanation_styles"],
            ["rigorous", "concise"],
        )
        self.assertEqual(
            [
                node["concept_id"]
                for node in context["current_subject_profile"]["knowledge_graph"][
                    "nodes"
                ]
            ],
            ["equation_setup"],
        )

    def test_summarizer_context_excludes_identity_and_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = StudentModelRepository(Path(temp_directory) / "state.db")
            model = repository.get_or_create("student_0", "high_school_1")
        payload = json.loads(
            build_student_model_summarizer_input(
                {
                    "lesson_plan": {"subject": "math"},
                    "solution": {"goal": "解题", "steps": []},
                    "teaching_progress": {},
                    "learning_evidence": [],
                    "open_question_history": [],
                    "conversation_summary": "",
                },
                model,
            )
        )

        self.assertNotIn("identity", payload["student_model"])
        self.assertNotIn("learning_profile", payload["student_model"])
        self.assertNotIn("academic_records", payload["student_model"])
        self.assertIn("current_subject_profile", payload["student_model"])

    def test_subject_level_fsm_limits_an_established_level_to_one_step(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = StudentModelRepository(Path(temp_directory) / "state.db")
            model = repository.get_or_create("student_0")
            model["subjects"]["math"]["level"]["state"] = "foundation"
            repository.save(model)
            patch = SubjectLevelPatch(
                subject="math",
                proposed_state="advanced",
                evidence_summary="多次综合题表现良好。",
                evidence_ids=["evidence_1", "evidence_2"],
                confidence="high",
            )
            updated = repository.apply_patch(
                model,
                StudentModelPatch(
                    base_model_version=1,
                    subject_level_updates=[patch],
                ),
            )

        self.assertEqual(
            updated["subjects"]["math"]["level"]["state"], "developing"
        )

    def test_advanced_student_starts_from_advanced_question(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = StudentModelRepository(Path(temp_directory) / "state.db")
            model = repository.get_or_create("student_0")
        model["subjects"]["math"]["level"]["state"] = "advanced"
        model["subjects"]["math"]["level"]["confidence"] = "high"
        solution = make_levelled_solution()
        policy = build_subject_level_policy(solution, model, "math")

        self.assertTrue(policy["skip_foundation_questions"])
        self.assertEqual(policy["deferred_question_ids"], ["question_0"])
        self.assertEqual(policy["recommended_entry_question_id"], "question_1")
        self.assertEqual(policy["recommended_entry_solution_step_id"], "step_1")

        payload = json.loads(
            build_teaching_planner_input(
                solution,
                VerificationReport(
                    verdict="passed",
                    summary="通过。",
                    checked_solution_step_ids=["step_0", "step_1"],
                    confidence="high",
                ),
                model,
                {},
                {
                    "lesson_plan": {"subject": "math"},
                    "teaching_progress": {},
                    "original_problem": {"status": "solved"},
                },
                policy,
            )
        )
        self.assertEqual(
            payload["subject_level_policy"]["recommended_entry_question_id"],
            "question_1",
        )
        self.assertIn("current_subject_profile", payload["student_model"])
        self.assertNotIn("subjects", payload["student_model"])
        self.assertEqual(
            set(payload["student_model"]["identity"]),
            {"display_name", "grade"},
        )

        wrong_entry = TeachingStrategy(
            strategy_id="strategy_0",
            summary="错误地从基础题开始。",
            initial_node_id="teach_0",
            nodes=[
                TeachingStrategyNode(
                    node_id="teach_0",
                    solution_step_id="step_0",
                    solution_question_id="question_0",
                    goal="基础审题",
                    teaching_action="ask_question",
                    prompt_intent="询问题目目标",
                    answer_checkpoints=["识别目标"],
                    disclosure_boundary="不透露答案",
                    transitions=[
                        TeachingTransition(condition="correct", action="advance"),
                        TeachingTransition(condition="partially_correct", next_node_id="teach_0", action="give_hint"),
                        TeachingTransition(condition="incorrect", next_node_id="teach_0", action="retry"),
                        TeachingTransition(condition="no_idea", next_node_id="teach_0", action="give_hint"),
                        TeachingTransition(condition="unclear", next_node_id="teach_0", action="retry"),
                        TeachingTransition(condition="student_requests_solution", action="complete"),
                    ],
                )
            ],
        )
        with self.assertRaisesRegex(ValueError, "subject-level entry question"):
            V02Orchestrator._validate_strategy_references(
                wrong_entry, solution, policy
            )

    def test_low_confidence_level_uses_standard_diagnostic_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = StudentModelRepository(Path(temp_directory) / "state.db")
            model = repository.get_or_create("student_0")
        model["subjects"]["math"]["level"]["state"] = "advanced"
        model["subjects"]["math"]["level"]["confidence"] = "low"

        policy = build_subject_level_policy(make_levelled_solution(), model, "math")

        self.assertEqual(policy["effective_level_state"], "unassessed")
        self.assertTrue(policy["skip_foundation_questions"])
        self.assertEqual(policy["recommended_entry_question_id"], "question_1")

    def test_v2_model_migrates_concepts_scores_and_preferences(self) -> None:
        now = datetime.now(timezone.utc).isoformat()
        legacy = {
            "student_id": "student_0",
            "schema_version": 2,
            "model_version": 4,
            "updated_at": now,
            "grade": "high_school_1",
            "identity": {"name": "小苏", "age": 16},
            "learning_history": {
                "concept_mastery": [
                    {
                        "concept_id": "quadratic_function",
                        "subject": "math",
                        "mastery": "proficient",
                        "updated_at": now,
                    }
                ],
                "persistent_misconceptions": [],
                "recent_attempts": [],
            },
            "score_map": {
                "recent_scores": [
                    {
                        "subject": "math",
                        "score": 120,
                        "max_score": 150,
                        "recorded_at": now,
                    }
                ]
            },
            "prefered_style": {
                "explanation_styles": ["concise"],
                "preferred_pace": "fast",
            },
            "meta_knowledge_cards": [],
        }
        with tempfile.TemporaryDirectory() as temp_directory:
            database = Path(temp_directory) / "state.db"
            repository = StudentModelRepository(database)
            with closing(sqlite3.connect(database)) as connection:
                with connection:
                    connection.execute(
                        """
                        INSERT INTO student_models(
                            student_id, schema_version, model_version, model_json,
                            created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        ("student_0", 2, 4, json.dumps(legacy), now, now),
                    )
            migrated = repository.get("student_0")

        self.assertEqual(migrated["schema_version"], 3)
        self.assertEqual(migrated["identity"]["display_name"], "小苏")
        self.assertEqual(
            migrated["subjects"]["math"]["knowledge_graph"]["nodes"][0][
                "concept_id"
            ],
            "quadratic_function",
        )
        self.assertEqual(migrated["academic_records"]["score_history"][0]["score"], 120)
        self.assertEqual(
            migrated["learning_profile"]["preferences"]["preferred_pace"], "fast"
        )

    def test_database_tracks_schema_metadata_and_version_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            database = Path(temp_directory) / "state.db"
            repository = StudentModelRepository(database)
            model = repository.get_or_create("student_0")
            with closing(sqlite3.connect(database)) as connection:
                columns = {
                    row[1]
                    for row in connection.execute(
                        "PRAGMA table_info(student_models)"
                    )
                }
            history = repository.get_version_history("student_0")

        self.assertTrue(
            {"schema_version", "model_version", "created_at", "updated_at"}
            <= columns
        )
        self.assertEqual(history[0]["change_source"], "create")
        self.assertEqual(history[0]["schema_version"], 3)
        self.assertEqual(model["model_version"], 1)

    def test_database_level_optimistic_lock_rejects_stale_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_directory:
            repository = StudentModelRepository(Path(temp_directory) / "state.db")
            stale = repository.get_or_create("student_0")
            patch = StudentModelPatch(
                base_model_version=1,
                subject_level_updates=[
                    SubjectLevelPatch(
                        subject="math",
                        proposed_state="developing",
                        evidence_summary="阶段性评估。",
                        evidence_ids=["assessment_1"],
                        confidence="medium",
                    )
                ],
            )
            repository.apply_patch(stale, patch)

            with self.assertRaisesRegex(ValueError, "version conflict"):
                repository.apply_patch(stale, patch)


if __name__ == "__main__":
    unittest.main()
