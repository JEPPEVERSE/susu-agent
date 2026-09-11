"""v0.3 题目结构投影。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


GoalType = Literal[
    "unknown",
    "extremum",
    "proof",
    "calculation",
    "construction",
    "solve",
    "range",
    "classification",
]
ProblemType = Literal[
    "unknown",
    "inequality",
    "function",
    "geometry",
    "equation",
    "trigonometry",
    "sequence",
    "probability",
    "statistics",
    "algebra",
    "analytic_geometry",
]


class ProblemRepresentation(BaseModel):
    """供求解、检索和教学规划共享的最小题目结构。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    problem_id: str = Field(min_length=1, max_length=200)
    subject: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=100)
    goal_type: GoalType = "unknown"
    problem_type: ProblemType = "unknown"
    objects: list[str] = Field(default_factory=list, max_length=50)
    conditions: list[str] = Field(default_factory=list, max_length=50)
    goal: str = Field(min_length=1, max_length=2_000)
    structural_features: dict[str, Any] = Field(default_factory=dict)
    concept_ids: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("goal_type", mode="before")
    @classmethod
    def normalize_goal_type(cls, value: Any) -> str:
        normalized = str(value or "unknown").strip().casefold()
        aliases = {
            "maximum": "extremum",
            "minimum": "extremum",
            "optimization": "extremum",
            "evaluate": "calculation",
            "compute": "calculation",
            "construct": "construction",
            "classification": "classification",
        }
        if normalized in aliases:
            return aliases[normalized]
        if any(marker in normalized for marker in ("最大", "最小", "最值", "极值")):
            return "extremum"
        if "证明" in normalized:
            return "proof"
        if any(marker in normalized for marker in ("求值", "计算")):
            return "calculation"
        if "构造" in normalized:
            return "construction"
        if any(marker in normalized for marker in ("范围", "值域")):
            return "range"
        if any(marker in normalized for marker in ("求解", "解方程")):
            return "solve"
        allowed = {
            "unknown", "extremum", "proof", "calculation", "construction",
            "solve", "range", "classification",
        }
        return normalized if normalized in allowed else "unknown"

    @field_validator("problem_type", mode="before")
    @classmethod
    def normalize_problem_type(cls, value: Any) -> str:
        normalized = str(value or "unknown").strip().casefold()
        marker_mapping = (
            (("三角", "trigonometric", "trigonometry"), "trigonometry"),
            (("解析几何", "analytic geometry"), "analytic_geometry"),
            (("不等式", "inequality"), "inequality"),
            (("函数", "function"), "function"),
            (("几何", "geometry", "三角形", "圆"), "geometry"),
            (("方程", "equation"), "equation"),
            (("数列", "sequence"), "sequence"),
            (("概率", "probability"), "probability"),
            (("统计", "statistics"), "statistics"),
            (("代数", "algebra"), "algebra"),
        )
        for markers, canonical in marker_mapping:
            if any(marker in normalized for marker in markers):
                return canonical
        allowed = {
            "unknown", "inequality", "function", "geometry", "equation",
            "trigonometry", "sequence", "probability", "statistics",
            "algebra", "analytic_geometry",
        }
        return normalized if normalized in allowed else "unknown"

    @field_validator("concept_ids")
    @classmethod
    def validate_concept_ids(cls, values: list[str]) -> list[str]:
        import re

        if len(values) != len(set(values)):
            raise ValueError("concept_ids must be unique")
        if any(not re.fullmatch(r"[a-z][a-z0-9_]*", value) for value in values):
            raise ValueError("concept_ids must be stable snake_case identifiers")
        return values

    @field_validator("objects", "conditions")
    @classmethod
    def validate_unique_text_items(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("problem structure items cannot be empty")
        if len(normalized) != len(set(normalized)):
            raise ValueError("problem structure items must be unique")
        return normalized
