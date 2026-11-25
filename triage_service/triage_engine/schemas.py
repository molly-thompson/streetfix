"""Application-agnostic Pydantic v2 schemas defining the triage JSON contract."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_DESCRIPTION_CHARS = 10_000
MAX_CONTEXT_NOTES_CHARS = 2_000
MAX_OVERRIDE_NOTES_CHARS = 500
MAX_METADATA_KEYS = 20


class TriageStatus(str, Enum):
    """Explicit processing outcome states for a triage evaluation."""

    COMPLETED = "completed"
    ABSTAINED = "abstained"
    DEGRADED = "degraded"


class QualitativeConfidence(str, Enum):
    """Qualitative confidence bands communicating estimated certainty."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class EvidenceQualityLevel(str, Enum):
    """Assessment of whether the supplied report contains sufficient detail."""

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"


class DecisionUncertaintyLevel(str, Enum):
    """Assessment of ambiguity across plausible categories, priorities, or teams."""

    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"


class MaterialImpact(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RoutingSource(str, Enum):
    CONFIGURED_RULE = "configured_rule"
    AI_ASSISTED = "ai_assisted"
    UNASSIGNED_FOR_REVIEW = "unassigned_for_review"


class HazardSource(str, Enum):
    SYSTEM_SAFEGUARD = "system_safeguard"
    ORG_POLICY = "org_policy"
    AI_FLAGGED = "ai_flagged"


class LocationInput(BaseModel):
    """Optional location context supplied with an issue report."""

    model_config = ConfigDict(extra="forbid")

    free_text: str | None = Field(default=None, max_length=500, description="Plain-text location description.")
    address: str | None = Field(default=None, max_length=300, description="Street address, building, or site name.")
    zone_or_ward: str | None = Field(default=None, max_length=150, description="Administrative zone, ward, or campus sector.")
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> LocationInput:
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Both latitude and longitude must be provided together.")
        return self

    def as_summary_text(self) -> str:
        parts = [p for p in [self.free_text, self.address, self.zone_or_ward] if p]
        if self.latitude is not None and self.longitude is not None:
            parts.append(f"({self.latitude:.5f}, {self.longitude:.5f})")
        return " | ".join(parts)


class ContextInput(BaseModel):
    """Optional contextual details surrounding an issue report."""

    model_config = ConfigDict(extra="forbid")

    reporter_role: str | None = Field(default=None, max_length=100, description="e.g. resident, student, staff, duty_officer.")
    channel: str | None = Field(default=None, max_length=80, description="Submission channel, e.g. web_form, chatbot, phone.")
    observed_at: str | None = Field(default=None, max_length=80, description="ISO timestamp or relative observation time.")
    recurring_issue: bool | None = Field(default=None, description="Whether the reporter notes this has happened repeatedly.")
    media_attached: bool | None = Field(default=None, description="Whether photos or attachments accompanied the report.")
    additional_notes: str | None = Field(default=None, max_length=MAX_CONTEXT_NOTES_CHARS)


class RequestConfigOverride(BaseModel):
    """
    Strictly allowlisted, non-weakening request-level configuration overrides.

    Requests may tighten oversight or add contextual prompts, but cannot
    disable safety criteria, weaken human-review rules, or supply credentials.
    """

    model_config = ConfigDict(extra="forbid")

    force_human_review: bool = Field(
        default=False,
        description="Require human review for this request regardless of threshold.",
    )
    stricter_confidence_floor: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Optional higher confidence threshold; cannot be lower than the org threshold.",
    )
    additional_missing_info_prompts: list[str] = Field(
        default_factory=list,
        max_length=5,
        description="Additional domain questions to check for in this request.",
    )
    contextual_notes: str | None = Field(
        default=None,
        max_length=MAX_OVERRIDE_NOTES_CHARS,
        description="Non-authoritative operational note appended as evaluation context.",
    )
    preferred_model_name: str | None = Field(
        default=None,
        max_length=100,
        description="Must match a model explicitly permitted in the target organisation profile.",
    )


class SharedReportInput(BaseModel):
    """Application-agnostic report payload used for single triage and multi-org comparison."""

    model_config = ConfigDict(extra="forbid")

    description: str = Field(
        ...,
        min_length=1,
        max_length=MAX_DESCRIPTION_CHARS,
        description="Required natural-language issue description.",
    )
    location: LocationInput | None = Field(default=None, description="Optional location context.")
    context: ContextInput | None = Field(default=None, description="Optional submission and situational context.")
    metadata: dict[str, str | int | float | bool] = Field(
        default_factory=dict,
        description="Optional opaque application metadata (bounded key-value pairs).",
    )

    @field_validator("description")
    @classmethod
    def description_must_not_be_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Issue description cannot be empty or whitespace only.")
        return cleaned

    @field_validator("metadata")
    @classmethod
    def validate_metadata_bounds(
        cls, value: dict[str, str | int | float | bool]
    ) -> dict[str, str | int | float | bool]:
        if len(value) > MAX_METADATA_KEYS:
            raise ValueError(f"metadata cannot contain more than {MAX_METADATA_KEYS} entries.")
        for k, v in value.items():
            if len(k) > 80:
                raise ValueError("metadata keys must be 80 characters or fewer.")
            if isinstance(v, str) and len(v) > 300:
                raise ValueError("metadata string values must be 300 characters or fewer.")
        return value


class TriageRequest(SharedReportInput):
    """Incoming request to triage a single issue report against one organisational profile."""

    profile_id: str = Field(
        default="streetfix",
        min_length=1,
        max_length=64,
        pattern=r"^[a-zA-Z0-9_-]+$",
        description="Organisational configuration profile identifier.",
    )
    config_override: RequestConfigOverride | None = Field(
        default=None,
        description="Optional, strictly allowlisted non-weakening request override.",
    )
    allow_degraded_on_ai_error: bool = Field(
        default=False,
        description=(
            "If true, upstream AI failures return an explicitly marked 'degraded' deterministic-only "
            "assessment instead of an HTTP 502/503/504 error."
        ),
    )


class TriageCompareRequest(BaseModel):
    """Submit an identical report across multiple organisational configurations for comparison."""

    model_config = ConfigDict(extra="forbid")

    report: SharedReportInput
    profile_ids: list[str] = Field(
        default_factory=lambda: ["streetfix", "campus_facilities"],
        min_length=2,
        max_length=5,
        description="Two or more distinct organisational profile IDs to compare.",
    )
    allow_degraded_on_ai_error: bool = Field(default=False)

    @field_validator("profile_ids")
    @classmethod
    def ensure_unique_profiles(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("profile_ids must be distinct.")
        return value


class CategoryCandidate(BaseModel):
    category_id: str
    category_name: str
    plausibility_note: str


class CategoryRecommendation(BaseModel):
    primary_category_id: str | None = None
    primary_category_name: str | None = None
    alternative_candidates: list[CategoryCandidate] = Field(default_factory=list)
    abstained: bool = False
    abstention_reason: str | None = None
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class PriorityRecommendation(BaseModel):
    priority_id: str | None = None
    priority_name: str | None = None
    rank: int | None = None
    escalated_by_safety: bool = False
    rationale: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)


class RoutingRecommendation(BaseModel):
    team_id: str | None = None
    team_name: str | None = None
    routing_source: RoutingSource
    rationale: str


class MatchedHazard(BaseModel):
    hazard_id: str
    label: str
    severity: Literal["critical", "high", "elevated"]
    source: HazardSource
    matched_text: str
    context_note: str


class NegatedOrUncertainMention(BaseModel):
    phrase: str
    assessment: Literal["negated", "uncertain_or_contradictory"]
    explanation: str


class SafetyAssessment(BaseModel):
    escalation_triggered: bool = False
    minimum_priority_enforced: str | None = None
    matched_hazards: list[MatchedHazard] = Field(default_factory=list)
    negated_or_uncertain_mentions: list[NegatedOrUncertainMention] = Field(default_factory=list)
    safety_warnings: list[str] = Field(default_factory=list)
    recommended_immediate_actions: list[str] = Field(default_factory=list)
    limitations_notice: str = (
        "Deterministic safety checks supplement review using configured patterns and contextual negation cues; "
        "they do not guarantee detection of every hazardous situation."
    )


class MissingInformationItem(BaseModel):
    field: str
    question: str
    reason: str
    material_impact: MaterialImpact


class EvidenceExcerpt(BaseModel):
    excerpt_id: str
    quote: str
    verified_in_source: bool
    verification_note: str | None = None
    supports_recommendations: list[str] = Field(default_factory=list)


class InferredConclusion(BaseModel):
    conclusion: str
    basis: str
    uncertainty_note: str | None = None
    explicitly_inferred: Literal[True] = True


class EvidenceAndReasoning(BaseModel):
    reported_facts: list[str] = Field(default_factory=list)
    evidence_excerpts: list[EvidenceExcerpt] = Field(default_factory=list)
    inferred_conclusions: list[InferredConclusion] = Field(default_factory=list)
    unsupported_or_contradictory_flags: list[str] = Field(default_factory=list)
    reasoning_summary: str


class ModelSelfAssessment(BaseModel):
    qualitative_level: QualitativeConfidence
    uncalibrated_estimate: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Model's own uncalibrated certainty estimate (0.0-1.0). Never a validated accuracy metric.",
    )
    calibration_disclaimer: str = (
        "Uncalibrated model self-estimate — not a statistically validated probability or accuracy guarantee."
    )


class EvidenceQualityAssessment(BaseModel):
    level: EvidenceQualityLevel
    explanation: str
    missing_critical_context: bool = False


class DecisionUncertaintyAssessment(BaseModel):
    level: DecisionUncertaintyLevel
    plausible_alternatives_exist: bool = False
    explanation: str
    ambiguities: list[str] = Field(default_factory=list)


class UncertaintyAssessment(BaseModel):
    model_self_assessment: ModelSelfAssessment
    evidence_quality: EvidenceQualityAssessment
    decision_uncertainty: DecisionUncertaintyAssessment
    abstained_dimensions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class HumanReviewAssessment(BaseModel):
    required: bool
    reasons: list[str] = Field(default_factory=list)
    recommended_reviewer_actions: list[str] = Field(default_factory=list)
    authority_notice: str = (
        "Decision support only: an authorised human officer must review and confirm "
        "category, priority, and routing before taking operational action."
    )


class ProviderMetadata(BaseModel):
    provider_name: str
    model_name: str
    ai_assessment_obtained: bool
    error_code: str | None = None
    error_detail: str | None = None


class TriageResponse(BaseModel):
    """Structured triage decision-support response returned by the engine."""

    request_id: str
    profile_used: str
    organisation_name: str
    status: TriageStatus
    category_recommendation: CategoryRecommendation
    priority_recommendation: PriorityRecommendation
    routing_recommendation: RoutingRecommendation
    safety_assessment: SafetyAssessment
    missing_information: list[MissingInformationItem] = Field(default_factory=list)
    evidence_and_reasoning: EvidenceAndReasoning
    uncertainty_assessment: UncertaintyAssessment
    human_review: HumanReviewAssessment
    provider_metadata: ProviderMetadata
    deterministic_rules_triggered: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ProfileComparisonDiff(BaseModel):
    dimension: str
    differs: bool
    summary: str
    values_by_profile: dict[str, str]


class TriageCompareResponse(BaseModel):
    comparison_id: str
    shared_description_preview: str
    shared_location_summary: str | None = None
    results_by_profile: dict[str, TriageResponse]
    safety_consistency_verified: bool
    comparison_diffs: list[ProfileComparisonDiff]
    policy_explanation: str


# --- Internal Structured Output Contract for AI Providers ---


class AIExtractedExcerpt(BaseModel):
    quote: str = Field(..., description="Exact verbatim substring copied from the user's report or location.")
    supports: list[str] = Field(
        default_factory=list,
        description="Which recommendations this quote supports, e.g. ['category', 'priority', 'safety'].",
    )


class AIInferredItem(BaseModel):
    conclusion: str
    basis: str
    uncertainty_note: str | None = None


class AIMissingInfoItem(BaseModel):
    field: str
    question: str
    reason: str
    material_impact: MaterialImpact


class AISafetyFlag(BaseModel):
    label: str
    severity: Literal["critical", "high", "elevated"]
    matched_text: str
    rationale: str


class AIAlternativeCategory(BaseModel):
    category_id: str
    plausibility_note: str


class AITriageRawOutput(BaseModel):
    """Schema requested from the LLM provider before deterministic reconciliation."""

    suggested_category_id: str | None = Field(
        default=None,
        description="Must match a configured category_id, or null if abstaining / out of scope.",
    )
    alternative_category_ids: list[AIAlternativeCategory] = Field(default_factory=list)
    abstain_category: bool = False
    abstention_reason: str | None = None

    suggested_priority_id: str | None = Field(
        default=None,
        description="Must match a configured priority_id, or null if insufficient information.",
    )
    priority_rationale: str

    suggested_team_id: str | None = Field(
        default=None,
        description="Optional team_id suggestion when routing allows AI assistance.",
    )
    routing_rationale: str

    reported_facts: list[str] = Field(
        default_factory=list,
        description="Facts explicitly stated in the input without extrapolation.",
    )
    evidence_excerpts: list[AIExtractedExcerpt] = Field(
        default_factory=list,
        description="Exact verbatim substrings copied directly from the input text.",
    )
    inferred_conclusions: list[AIInferredItem] = Field(
        default_factory=list,
        description="Interpretations or inferences derived from the reported facts.",
    )
    contradictions_or_ambiguities: list[str] = Field(default_factory=list)
    reasoning_summary: str

    ai_safety_flags: list[AISafetyFlag] = Field(default_factory=list)
    missing_information: list[AIMissingInfoItem] = Field(default_factory=list)

    model_qualitative_confidence: QualitativeConfidence
    model_uncalibrated_estimate: float = Field(..., ge=0.0, le=1.0)
    evidence_quality: EvidenceQualityLevel
    evidence_quality_explanation: str
    decision_uncertainty: DecisionUncertaintyLevel
    decision_uncertainty_explanation: str
    recommend_human_review: bool
    human_review_reasons: list[str] = Field(default_factory=list)
