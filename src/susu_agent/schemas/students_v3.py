"""StudentModel v3 的结构化 Schema 与有限状态定义。"""

from typing import Any, Literal, Self

from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, model_validator

from susu_agent.schemas.format_checkers import ISO_DATETIME_FORMAT_CHECKER


SUBJECTS = ("math", "chinese", "english", "physics", "chemistry", "biology")
SubjectCode = Literal["math", "chinese", "english", "physics", "chemistry", "biology"]
SubjectLevelState = Literal[
    "unassessed", "foundation", "developing", "proficient", "advanced"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class IdentityProfile(StrictModel):
    display_name: str | None = Field(default=None, max_length=50)
    grade: str = Field(default="unknown", min_length=1, max_length=50)
    class_name: str | None = Field(default=None, max_length=100)
    school_name: str | None = Field(default=None, max_length=200)
    student_number: str | None = Field(default=None, max_length=100)
    age: int | None = Field(default=None, ge=0, le=120)
    region: str | None = Field(default=None, max_length=100)
    phone_number: str | None = Field(default=None, max_length=30)
    email_address: str | None = Field(default=None, max_length=254)


class SubjectLevel(StrictModel):
    state: SubjectLevelState = "unassessed"
    confidence: Literal["low", "medium", "high"] = "low"
    evidence_summary: str = Field(default="", max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    updated_at: str | None = Field(default=None, json_schema_extra={"format": "date-time"})


class KnowledgeNode(StrictModel):
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    name: str | None = Field(default=None, max_length=200)
    mastery: Literal["unknown", "learning", "proficient", "mastered"] = "unknown"
    evidence_summary: str = Field(default="", max_length=500)
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    prerequisite_ids: list[str] = Field(default_factory=list, max_length=30)
    updated_at: str | None = Field(default=None, json_schema_extra={"format": "date-time"})


class KnowledgeEdge(StrictModel):
    source_concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    target_concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    relation: Literal["prerequisite", "related", "part_of"]


class SubjectKnowledgeGraph(StrictModel):
    nodes: list[KnowledgeNode] = Field(default_factory=list, max_length=500)
    edges: list[KnowledgeEdge] = Field(default_factory=list, max_length=1_000)

    @model_validator(mode="after")
    def validate_graph(self) -> Self:
        node_ids = [node.concept_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("Knowledge graph concept ids must be unique per subject.")
        known = set(node_ids)
        edge_keys = [
            (edge.source_concept_id, edge.target_concept_id, edge.relation)
            for edge in self.edges
        ]
        if len(edge_keys) != len(set(edge_keys)):
            raise ValueError("Knowledge graph edges must be unique.")
        unknown = {
            concept_id
            for edge in self.edges
            for concept_id in (edge.source_concept_id, edge.target_concept_id)
            if concept_id not in known
        }
        if unknown:
            raise ValueError(f"Knowledge graph edges reference unknown concepts: {unknown!r}.")
        return self


class SubjectProfile(StrictModel):
    level: SubjectLevel = Field(default_factory=SubjectLevel)
    strengths: list[str] = Field(default_factory=list, max_length=20)
    weaknesses: list[str] = Field(default_factory=list, max_length=20)
    knowledge_graph: SubjectKnowledgeGraph = Field(default_factory=SubjectKnowledgeGraph)
    notes: str = Field(default="", max_length=1_000)


class SixSubjectProfiles(StrictModel):
    math: SubjectProfile
    chinese: SubjectProfile
    english: SubjectProfile
    physics: SubjectProfile
    chemistry: SubjectProfile
    biology: SubjectProfile


class LearningPreferences(StrictModel):
    explanation_styles: list[
        Literal[
            "socratic",
            "visual",
            "step_by_step",
            "example_first",
            "concise",
            "rigorous",
            "key_point_first",
        ]
    ] = Field(default_factory=list, max_length=5)
    preferred_pace: Literal["unknown", "slow", "normal", "fast"] = "unknown"
    interaction_style: Literal["unknown", "reserved", "balanced", "active"] = "unknown"
    challenge_preference: Literal["unknown", "guided", "balanced", "challenging"] = (
        "unknown"
    )
    notes: str = Field(default="", max_length=1_000)


class LearningProfile(StrictModel):
    strength_subjects: list[SubjectCode] = Field(default_factory=list, max_length=6)
    support_subjects: list[SubjectCode] = Field(default_factory=list, max_length=6)
    learning_styles: list[
        Literal["visual", "auditory", "reading_writing", "practice_driven", "mixed"]
    ] = Field(default_factory=list, max_length=5)
    learning_engagement: Literal["unknown", "low", "medium", "high"] = "unknown"
    preferences: LearningPreferences = Field(default_factory=LearningPreferences)


class PersistentMisconception(StrictModel):
    concept_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    subject: SubjectCode
    description: str = Field(min_length=1, max_length=300)
    occurrences: int = Field(ge=1)
    last_seen_at: str = Field(json_schema_extra={"format": "date-time"})


class LearningHistory(StrictModel):
    persistent_misconceptions: list[PersistentMisconception] = Field(
        default_factory=list, max_length=100
    )
    recent_attempts: list[str] = Field(default_factory=list, max_length=20)


class ScoreRecord(StrictModel):
    subject: SubjectCode
    score: float = Field(ge=0)
    max_score: float = Field(gt=0)
    assessment_name: str | None = Field(default=None, max_length=100)
    exam_type: str | None = Field(default=None, max_length=100)
    class_rank: int | None = Field(default=None, ge=1)
    grade_rank: int | None = Field(default=None, ge=1)
    recorded_at: str = Field(json_schema_extra={"format": "date-time"})


class AcademicRecords(StrictModel):
    score_history: list[ScoreRecord] = Field(default_factory=list, max_length=2_000)
    latest_import_id: str | None = Field(default=None, max_length=100)
    latest_imported_at: str | None = Field(
        default=None, json_schema_extra={"format": "date-time"}
    )


class GaokaoGoal(StrictModel):
    exam_year: int | None = Field(default=None, ge=2000, le=2200)
    target_total_score: float | None = Field(default=None, ge=0)
    target_subject_scores: dict[SubjectCode, float | None] = Field(default_factory=dict)
    notes: str = Field(default="", max_length=1_000)


class TargetInstitution(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    priority: Literal["reach", "target", "safety", "unspecified"] = "unspecified"
    program: str | None = Field(default=None, max_length=200)
    notes: str = Field(default="", max_length=1_000)


class EducationGoals(StrictModel):
    gaokao: GaokaoGoal = Field(default_factory=GaokaoGoal)
    target_institutions: list[TargetInstitution] = Field(default_factory=list, max_length=30)


class MetaKnowledgeCard(StrictModel):
    card_id: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=1_000)
    evidence_ids: list[str] = Field(default_factory=list, max_length=30)
    updated_at: str = Field(json_schema_extra={"format": "date-time"})


class StudentModelV3(StrictModel):
    student_id: str = Field(min_length=1, max_length=100)
    schema_version: Literal[3] = 3
    model_version: int = Field(ge=1)
    updated_at: str = Field(json_schema_extra={"format": "date-time"})
    identity: IdentityProfile
    learning_profile: LearningProfile
    subjects: SixSubjectProfiles
    learning_history: LearningHistory
    academic_records: AcademicRecords
    education_goals: EducationGoals
    meta_knowledge_cards: list[MetaKnowledgeCard] = Field(default_factory=list, max_length=200)
    extensions: dict[str, Any] = Field(default_factory=dict)


STUDENT_MODEL_SCHEMA: dict[str, Any] = StudentModelV3.model_json_schema()
STUDENT_MODEL_VALIDATOR = Draft202012Validator(
    STUDENT_MODEL_SCHEMA,
    format_checker=ISO_DATETIME_FORMAT_CHECKER,
)


def validate_student_model(student_model: dict[str, Any]) -> None:
    """校验完整 StudentModel v3，不符合 schema 时抛出 ValidationError。"""
    STUDENT_MODEL_VALIDATOR.validate(student_model)
    StudentModelV3.model_validate(student_model)
