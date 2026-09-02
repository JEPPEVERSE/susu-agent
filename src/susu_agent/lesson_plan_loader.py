"""按学科 JSON 清单加载教案文件。"""

import json
import logging
import re
from hashlib import sha256
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_LESSON_PLANS_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "lesson_plans"
)
_SUBJECT_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class LessonPlanStep:
    """教案清单中可被 TeachingState 引用的一个稳定步骤。"""

    step_id: str
    name: str
    context_headings: tuple[str, ...]

    @property
    def label(self) -> str:
        return f"{self.step_id} {self.name}"


@dataclass(frozen=True, slots=True)
class LessonPlanContextSelection:
    """按当前教案步骤检索出的有限理论上下文。"""

    step_id: str
    content: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class LessonPlanBundle:
    """一次加载后可分别提供给 instruction 和模型上下文的教案。"""

    subject: str
    manifest_schema_version: int
    lesson_plan_version: str
    instruction: str
    context: str
    instruction_sources: tuple[str, ...]
    context_sources: tuple[str, ...]
    steps: tuple[LessonPlanStep, ...]
    always_include_context_headings: tuple[str, ...]
    context_sections: dict[str, tuple[str, str]]
    content_digest: str

    @property
    def default_step_id(self) -> str:
        return self.steps[0].step_id

    @property
    def step_ids(self) -> tuple[str, ...]:
        return tuple(step.step_id for step in self.steps)

    def get_step(self, step_id: str) -> LessonPlanStep:
        for step in self.steps:
            if step.step_id == step_id:
                return step
        raise ValueError(
            f"Unknown lesson plan step {step_id!r} for subject {self.subject!r}."
        )

    def select_context(self, step_id: str | None) -> LessonPlanContextSelection:
        """按步骤清单选择全局章节和当前步骤章节。"""
        selected_step_id = step_id or self.default_step_id
        step = self.get_step(selected_step_id)
        headings = _unique_preserving_order(
            (*self.always_include_context_headings, *step.context_headings)
        )
        sections: list[str] = []
        sources: list[str] = []
        for heading in headings:
            source, content = self.context_sections[heading]
            sections.append(content)
            if source not in sources:
                sources.append(source)
        return LessonPlanContextSelection(
            step_id=selected_step_id,
            content="\n\n".join(sections),
            sources=tuple(sources),
        )


class LessonPlanLoader:
    """根据学科 JSON 清单依次组合明确登记的 Markdown 教案。"""

    def __init__(self, lesson_plans_directory: Path | None = None) -> None:
        self._lesson_plans_directory = (
            lesson_plans_directory or DEFAULT_LESSON_PLANS_DIRECTORY
        ).resolve()

    def load(self, subject: str) -> LessonPlanBundle:
        """加载指定学科；文件合并顺序完全由 JSON 数组决定。"""
        subject_directory = self._resolve_subject_directory(subject)
        manifest = self._load_manifest(subject_directory)

        manifest_schema_version = manifest.get("schema_version")
        if manifest_schema_version != 1:
            raise ValueError("Only lesson plan schema_version 1 is supported.")

        manifest_subject = manifest.get("subject")
        if manifest_subject != subject:
            raise ValueError(
                "Lesson plan manifest subject does not match directory: "
                f"expected {subject!r}, got {manifest_subject!r}."
            )

        lesson_plan_version = manifest.get("lesson_plan_version")
        if not isinstance(lesson_plan_version, str) or not re.fullmatch(
            r"[0-9]+\.[0-9]+\.[0-9]+",
            lesson_plan_version,
        ):
            raise ValueError(
                "Manifest field 'lesson_plan_version' must use MAJOR.MINOR.PATCH."
            )

        steps = self._load_steps(manifest)
        always_include_context_headings = self._load_heading_list(
            manifest,
            "always_include_context_headings",
            allow_empty=True,
        )

        instruction_documents = self._load_documents(
            subject_directory,
            manifest,
            files_key="instruction_files",
        )
        context_documents = self._load_documents(
            subject_directory,
            manifest,
            files_key="context_files",
        )

        instruction = self._combine_documents(instruction_documents)
        context = self._combine_documents(context_documents)
        instruction_sources = tuple(
            self._display_path(path) for path, _ in instruction_documents
        )
        context_sources = tuple(
            self._display_path(path) for path, _ in context_documents
        )
        context_sections = self._build_context_sections(context_documents)
        required_headings = _unique_preserving_order(
            (
                *always_include_context_headings,
                *(heading for step in steps for heading in step.context_headings),
            )
        )
        missing_headings = [
            heading for heading in required_headings if heading not in context_sections
        ]
        if missing_headings:
            raise ValueError(
                "Lesson plan context headings were not found: "
                + ", ".join(repr(heading) for heading in missing_headings)
            )
        content_digest = sha256(
            json.dumps(
                {
                    "subject": subject,
                    "manifest_schema_version": manifest_schema_version,
                    "lesson_plan_version": lesson_plan_version,
                    "instruction_sources": instruction_sources,
                    "context_sources": context_sources,
                    "steps": [
                        {
                            "id": step.step_id,
                            "name": step.name,
                            "context_headings": step.context_headings,
                        }
                        for step in steps
                    ],
                    "always_include_context_headings": (
                        always_include_context_headings
                    ),
                    "instruction": instruction,
                    "context": context,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

        lesson_plan = LessonPlanBundle(
            subject=subject,
            manifest_schema_version=manifest_schema_version,
            lesson_plan_version=lesson_plan_version,
            instruction=instruction,
            context=context,
            instruction_sources=instruction_sources,
            context_sources=context_sources,
            steps=steps,
            always_include_context_headings=always_include_context_headings,
            context_sections=context_sections,
            content_digest=content_digest,
        )
        logger.debug(
            "Loaded lesson plan for subject %s (version %s, %d steps)",
            lesson_plan.subject,
            lesson_plan.lesson_plan_version,
            len(lesson_plan.steps),
        )
        return lesson_plan

    @staticmethod
    def _load_steps(manifest: dict[str, Any]) -> tuple[LessonPlanStep, ...]:
        raw_steps = manifest.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ValueError("Manifest field 'steps' must be a non-empty list.")

        steps: list[LessonPlanStep] = []
        seen_ids: set[str] = set()
        for raw_step in raw_steps:
            if not isinstance(raw_step, dict):
                raise ValueError("Every lesson plan step must be an object.")
            step_id = raw_step.get("id")
            name = raw_step.get("name")
            if not isinstance(step_id, str) or not re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_-]{0,99}",
                step_id,
            ):
                raise ValueError(f"Invalid lesson plan step id: {step_id!r}")
            if step_id in seen_ids:
                raise ValueError(f"Duplicate lesson plan step id: {step_id!r}")
            if not isinstance(name, str) or not name.strip() or len(name) > 200:
                raise ValueError(f"Invalid lesson plan step name: {name!r}")
            context_headings = LessonPlanLoader._load_heading_list(
                raw_step,
                "context_headings",
                allow_empty=False,
            )
            seen_ids.add(step_id)
            steps.append(
                LessonPlanStep(
                    step_id=step_id,
                    name=name.strip(),
                    context_headings=context_headings,
                )
            )
        return tuple(steps)

    @staticmethod
    def _load_heading_list(
        container: dict[str, Any],
        key: str,
        *,
        allow_empty: bool,
    ) -> tuple[str, ...]:
        raw_headings = container.get(key)
        if not isinstance(raw_headings, list) or (
            not allow_empty and not raw_headings
        ):
            expectation = "a list" if allow_empty else "a non-empty list"
            raise ValueError(f"Field {key!r} must be {expectation}.")
        headings: list[str] = []
        for heading in raw_headings:
            if not isinstance(heading, str) or not heading.strip():
                raise ValueError(f"Every entry in {key!r} must be a string.")
            normalized_heading = heading.strip()
            if normalized_heading in headings:
                raise ValueError(f"Duplicate heading in {key!r}: {heading!r}")
            headings.append(normalized_heading)
        return tuple(headings)

    def _build_context_sections(
        self,
        documents: list[tuple[Path, str]],
    ) -> dict[str, tuple[str, str]]:
        sections: dict[str, tuple[str, str]] = {}
        for path, content in documents:
            source = self._display_path(path)
            for heading, section in _split_markdown_sections(content):
                if heading in sections:
                    raise ValueError(
                        f"Duplicate context heading across lesson plan files: {heading!r}"
                    )
                sections[heading] = (source, section)
        return sections

    def list_subjects(self) -> tuple[str, ...]:
        """列出包含合法教案清单的学科目录。"""
        if not self._lesson_plans_directory.is_dir():
            return ()
        return tuple(
            path.name
            for path in sorted(self._lesson_plans_directory.iterdir())
            if path.is_dir()
            and _SUBJECT_PATTERN.fullmatch(path.name)
            and (path / "lesson_plan.json").is_file()
        )

    def _resolve_subject_directory(self, subject: str) -> Path:
        if not _SUBJECT_PATTERN.fullmatch(subject):
            raise ValueError(
                "subject must start with a lowercase letter and contain only "
                "lowercase letters, numbers, underscores, or hyphens."
            )

        subject_directory = (self._lesson_plans_directory / subject).resolve()
        if not subject_directory.is_relative_to(self._lesson_plans_directory):
            raise ValueError("Subject directory escapes lesson_plans.")
        if not subject_directory.is_dir():
            raise FileNotFoundError(
                f"Lesson plan subject directory does not exist: {subject_directory}"
            )
        return subject_directory

    @staticmethod
    def _load_manifest(subject_directory: Path) -> dict[str, Any]:
        manifest_path = subject_directory / "lesson_plan.json"
        if not manifest_path.is_file():
            raise FileNotFoundError(
                f"Lesson plan manifest does not exist: {manifest_path}"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Lesson plan manifest is not valid JSON: {manifest_path}"
            ) from error
        if not isinstance(manifest, dict):
            raise ValueError("Lesson plan manifest must be a JSON object.")
        return manifest

    def _load_documents(
        self,
        subject_directory: Path,
        manifest: dict[str, Any],
        *,
        files_key: str,
    ) -> list[tuple[Path, str]]:
        file_values = manifest.get(files_key)
        if not isinstance(file_values, list) or not file_values:
            raise ValueError(
                f"Manifest field {files_key!r} must be a non-empty path list."
            )

        documents: list[tuple[Path, str]] = []
        seen_paths: set[Path] = set()
        for value in file_values:
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"Every entry in {files_key!r} must be a path string."
                )
            path = self._resolve_inside_subject(subject_directory, value)
            if path in seen_paths:
                raise ValueError(
                    f"Duplicate lesson plan file in {files_key!r}: {value!r}"
                )
            seen_paths.add(path)
            documents.append((path, self._read_markdown(path)))
        return documents

    @staticmethod
    def _resolve_inside_subject(subject_directory: Path, value: str) -> Path:
        path = (subject_directory / value).resolve()
        if not path.is_relative_to(subject_directory):
            raise ValueError(
                f"Lesson plan path escapes its subject directory: {value!r}"
            )
        return path

    @staticmethod
    def _read_markdown(path: Path) -> str:
        if path.suffix.lower() != ".md" or not path.is_file():
            raise FileNotFoundError(
                f"Lesson plan Markdown file does not exist: {path}"
            )
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            raise ValueError(f"Lesson plan Markdown file is empty: {path}")
        return content

    def _display_path(self, path: Path) -> str:
        return path.relative_to(self._lesson_plans_directory).as_posix()

    def _combine_documents(
        self,
        documents: list[tuple[Path, str]],
    ) -> str:
        sections: list[str] = []
        for index, (path, content) in enumerate(documents):
            if index == 0:
                sections.append(content)
                continue
            sections.append(
                f"<!-- lesson-plan-patch: {self._display_path(path)} -->\n\n"
                f"{content}"
            )
        return "\n\n".join(sections)


def load_lesson_plan(
    subject: str,
    lesson_plans_directory: Path | None = None,
) -> LessonPlanBundle:
    """供业务代码统一调用的教案加载入口。"""
    return LessonPlanLoader(lesson_plans_directory).load(subject)


def _split_markdown_sections(content: str) -> list[tuple[str, str]]:
    """按二至四级标题拆分 Markdown，并保留标题本身。"""
    lines = content.splitlines()
    heading_entries: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines):
        match = re.match(r"^(#{2,4})\s+(.+?)\s*$", line)
        if match:
            heading_entries.append((index, len(match.group(1)), match.group(2)))

    sections: list[tuple[str, str]] = []
    for entry_index, (start, level, heading) in enumerate(heading_entries):
        end = len(lines)
        for next_start, next_level, _ in heading_entries[entry_index + 1 :]:
            if next_level <= level:
                end = next_start
                break
        sections.append((heading, "\n".join(lines[start:end]).strip()))
    return sections


def _unique_preserving_order(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))
