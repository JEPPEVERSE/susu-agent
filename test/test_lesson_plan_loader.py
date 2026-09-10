import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.lesson_plan_loader import LessonPlanLoader


class LessonPlanLoaderTests(unittest.TestCase):
    def test_project_math_lesson_plan_is_available(self) -> None:
        lesson_plan = LessonPlanLoader().load("math")

        self.assertEqual(lesson_plan.subject, "math")
        self.assertEqual(lesson_plan.manifest_schema_version, 1)
        self.assertEqual(lesson_plan.lesson_plan_version, "2.0.0")
        self.assertEqual(lesson_plan.step_ids, tuple(f"S{i}" for i in range(1, 10)))
        self.assertEqual(len(lesson_plan.content_digest), 64)
        self.assertIn("S1 明确研究对象与交付目标", lesson_plan.instruction)
        self.assertIn("要素关系网", lesson_plan.context)
        self.assertEqual(
            lesson_plan.instruction_sources,
            ("math/instruction.md",),
        )
        self.assertEqual(
            lesson_plan.context_sources,
            ("math/context.md",),
        )
        selected_context = lesson_plan.select_context("S3")
        self.assertIn("系统与自由度", selected_context.content)
        self.assertNotIn("F8 即时检查", selected_context.content)
        self.assertLess(len(selected_context.content), len(lesson_plan.context))

    def test_manifest_order_is_used_and_unlisted_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            lesson_plans_directory = Path(temporary_directory)
            subject_directory = lesson_plans_directory / "math"
            instruction_patches = subject_directory / "patches" / "instruction"
            context_patches = subject_directory / "patches" / "context"
            instruction_patches.mkdir(parents=True)
            context_patches.mkdir(parents=True)

            (subject_directory / "instruction.md").write_text(
                "base instruction",
                encoding="utf-8",
            )
            (subject_directory / "context.md").write_text(
                "## Base Context\n\nbase context",
                encoding="utf-8",
            )
            (instruction_patches / "020_second.md").write_text(
                "second patch",
                encoding="utf-8",
            )
            (instruction_patches / "010_first.md").write_text(
                "first patch",
                encoding="utf-8",
            )
            (instruction_patches / "_README.md").write_text(
                "maintenance only",
                encoding="utf-8",
            )
            manifest = {
                "schema_version": 1,
                "subject": "math",
                "lesson_plan_version": "0.1.0",
                "instruction_files": [
                    "instruction.md",
                    "patches/instruction/020_second.md",
                    "patches/instruction/010_first.md",
                ],
                "context_files": ["context.md"],
                "always_include_context_headings": [],
                "steps": [
                    {
                        "id": "S1",
                        "name": "Start",
                        "context_headings": ["Base Context"],
                    }
                ],
            }
            (subject_directory / "lesson_plan.json").write_text(
                json.dumps(manifest),
                encoding="utf-8",
            )

            lesson_plan = LessonPlanLoader(lesson_plans_directory).load("math")

        self.assertLess(
            lesson_plan.instruction.index("second patch"),
            lesson_plan.instruction.index("first patch"),
        )
        self.assertNotIn("maintenance only", lesson_plan.instruction)
        self.assertEqual(
            lesson_plan.instruction_sources,
            (
                "math/instruction.md",
                "math/patches/instruction/020_second.md",
                "math/patches/instruction/010_first.md",
            ),
        )

    def test_invalid_subject_path_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            LessonPlanLoader().load("../math")


if __name__ == "__main__":
    unittest.main()
