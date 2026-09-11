"""v0.3 题目结构投影。"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProblemRepresentation(BaseModel):
    """供求解、检索和教学规划共享的最小题目结构。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1] = 1
    problem_id: str = Field(min_length=1, max_length=200)
    subject: str = Field(pattern=r"^[a-z][a-z0-9_-]*$", max_length=100)
    goal_type: str = Field(default="unknown", min_length=1, max_length=100)
    problem_type: str = Field(default="unknown", min_length=1, max_length=100)
    objects: list[str] = Field(default_factory=list, max_length=50)
    conditions: list[str] = Field(default_factory=list, max_length=50)
    goal: str = Field(min_length=1, max_length=2_000)
    structural_features: dict[str, Any] = Field(default_factory=dict)
    concept_ids: list[str] = Field(default_factory=list, max_length=50)

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
