import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from susu_agent.lesson_plan_loader import LessonPlanLoader
from susu_agent.lesson_plan_rag import LessonPlanPatchCatalog, LessonPlanPatchRAG, PatchQuery


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class LessonPlanPatchRAGTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name) / "lesson_plans"
        shutil.copytree(PROJECT_ROOT / "lesson_plans" / "math", self.root / "math")
        self.lesson_plan = LessonPlanLoader(self.root).load("math")

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    def _write_patch(
        self,
        filename: str,
        *,
        kind: str = "context",
        patch_id: str = "math.open_interval",
        title: str = "开区间最值",
        summary: str = "区分最大值和上确界。",
        agents: str = '"teaching_planner", "teaching_executor"',
        steps: str = '"S2", "S7"',
        concepts: str = '"open_interval_extrema"',
        keywords: str = '"开区间", "最大值", "上确界"',
        knowledge: str = '"开区间 | 需要检查 | 端点可取性"',
        body: str = "# 开区间最值\n\n先检查端点是否属于定义域，再区分最大值与上确界。",
    ) -> Path:
        path = self.root / "math" / "patches" / kind / filename
        path.write_text(
            "\n".join(
                (
                    "+++",
                    f'patch_id = "{patch_id}"',
                    'version = "1.0.0"',
                    f'kind = "{kind}"',
                    f'title = "{title}"',
                    f'summary = "{summary}"',
                    f"target_agents = [{agents}]",
                    f"step_ids = [{steps}]",
                    f"concept_ids = [{concepts}]",
                    f"keywords = [{keywords}]",
                    "priority = 60",
                    "enabled = true",
                    f"knowledge = [{knowledge}]",
                    "+++",
                    "",
                    body,
                )
            ),
            encoding="utf-8",
        )
        return path

    def test_chinese_query_retrieves_relevant_patch_and_tracks_source(self) -> None:
        self._write_patch("open_interval.md")
        self._write_patch(
            "vectors.md",
            patch_id="math.vector_projection",
            title="向量投影",
            summary="处理向量投影与夹角。",
            steps='"S4"',
            concepts='"vector_projection"',
            keywords='"向量", "投影"',
            knowledge='"向量 | 可以投影到 | 坐标轴"',
            body="# 向量投影\n\n使用点积计算投影。",
        )

        result = LessonPlanPatchRAG(self.root).retrieve(
            PatchQuery(
                subject="math",
                agent="teaching_planner",
                text="开区间上的最大值是否一定能取到？",
                step_ids=("S7",),
            ),
            self.lesson_plan,
        )

        self.assertEqual(result.matches[0].patch.patch_id, "math.open_interval")
        self.assertIn("开区间 | 需要检查 | 端点可取性", result.matches[0].reasoning_path)
        prompt = result.to_prompt()
        self.assertIn("math/patches/context/open_interval.md", prompt)
        self.assertIn("先检查端点", prompt)

    def test_knowledge_edges_expand_candidates_across_two_hops(self) -> None:
        self._write_patch("open_interval.md")
        self._write_patch(
            "supremum.md",
            patch_id="math.supremum",
            title="上确界判定",
            summary="判断边界值是否实际取得。",
            steps='"S8"',
            concepts='"supremum"',
            keywords='"上确界"',
            knowledge='"端点可取性 | 用于区分 | 上确界"',
            body="# 上确界判定\n\n不可取的边界值可以是上确界，但不是最大值。",
        )

        result = LessonPlanPatchRAG(self.root).retrieve(
            PatchQuery(
                subject="math",
                agent="teaching_executor",
                text="开区间最值",
                max_hops=2,
            ),
            self.lesson_plan,
        )

        ids = [match.patch.patch_id for match in result.matches]
        self.assertIn("math.open_interval", ids)
        self.assertIn("math.supremum", ids)
        supremum = next(match for match in result.matches if match.patch.patch_id == "math.supremum")
        self.assertIn("端点可取性 | 用于区分 | 上确界", supremum.reasoning_path)

    def test_target_agent_is_a_hard_filter(self) -> None:
        self._write_patch("open_interval.md", agents='"teaching_planner"')

        result = LessonPlanPatchRAG(self.root).retrieve(
            PatchQuery(
                subject="math",
                agent="solution_verifier",
                text="开区间最大值",
            ),
            self.lesson_plan,
        )

        self.assertEqual(result.matches, ())

    def test_invalid_patch_step_is_rejected_before_retrieval(self) -> None:
        self._write_patch("invalid.md", steps='"S404"')

        with self.assertRaisesRegex(ValueError, "Unknown step_ids"):
            LessonPlanPatchCatalog(self.root).load(self.lesson_plan)

    def test_query_step_is_validated_in_code(self) -> None:
        self._write_patch("open_interval.md")

        with self.assertRaisesRegex(ValueError, "unknown step ids"):
            LessonPlanPatchRAG(self.root).retrieve(
                PatchQuery(
                    subject="math",
                    agent="teaching_planner",
                    text="最值",
                    step_ids=("S404",),
                ),
                self.lesson_plan,
            )

    def test_prompt_respects_patch_content_budget(self) -> None:
        self._write_patch(
            "long.md",
            body="# 很长的补丁\n\n" + "开区间边界检查。" * 300,
        )

        result = LessonPlanPatchRAG(self.root).retrieve(
            PatchQuery(
                subject="math",
                agent="teaching_planner",
                text="开区间最大值",
                max_context_chars=500,
            ),
            self.lesson_plan,
        )

        prompt = result.to_prompt()
        self.assertIn("math.open_interval", prompt)
        self.assertIn("…", prompt)
        self.assertLess(len(prompt), 900)

    def test_empty_patch_directories_return_an_empty_result(self) -> None:
        result = LessonPlanPatchRAG(self.root).retrieve(
            PatchQuery(
                subject="math",
                agent="teaching_planner",
                text="任意问题",
            ),
            self.lesson_plan,
        )

        self.assertEqual(result.matches, ())
        self.assertEqual(result.to_prompt(), "")


if __name__ == "__main__":
    unittest.main()
