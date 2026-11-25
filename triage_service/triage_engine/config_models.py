"""Organisational triage configuration schemas and cross-reference validation."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SUPPORTED_PROVIDERS = {"gemini"}
DISALLOWED_DEPRECATED_MODELS = {
    "gemini-1.5-flash",
    "gemini-1.5-pro",
    "gemini-pro",
    "gemini-2.0-flash",
    "gemini-2.0-pro",
    "gemini-2.0-flash-thinking",
}


class AISettingsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str = Field(default="gemini")
    model_name: str = Field(default="gemini-4-hydrogen")
    permitted_models: list[str] = Field(
        default_factory=lambda: ["gemini-4-hydrogen", "gemini-4-neon", "gemini-3.1-flash-lite"]
    )
    thinking_level: Literal["low", "medium", "high"] | None = Field(default="low")
    timeout_seconds: float = Field(default=25.0, ge=2.0, le=60.0)

    @field_validator("provider")
    @classmethod
    def validate_provider(cls, value: str) -> str:
        lowered = value.strip().lower()
        if lowered not in SUPPORTED_PROVIDERS:
            raise ValueError(
                f"Unsupported AI provider '{value}'. Supported providers: {sorted(SUPPORTED_PROVIDERS)}."
            )
        return lowered

    @field_validator("model_name")
    @classmethod
    def validate_model_not_deprecated(cls, value: str) -> str:
        if value in DISALLOWED_DEPRECATED_MODELS:
            raise ValueError(f"Model '{value}' is deprecated and not permitted.")
        return value

    @model_validator(mode="after")
    def validate_model_in_permitted(self) -> AISettingsConfig:
        for model in self.permitted_models:
            if model in DISALLOWED_DEPRECATED_MODELS:
                raise ValueError(f"Permitted model list contains deprecated model '{model}'.")
        if self.model_name not in self.permitted_models:
            raise ValueError(
                f"Default model_name '{self.model_name}' must be included in permitted_models {self.permitted_models}."
            )
        return self


class CategoryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(..., min_length=5, max_length=500)
    examples: list[str] = Field(default_factory=list)
    requires_location: bool = Field(default=True)
    always_require_human_review: bool = Field(default=False)


class PriorityLevelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(..., min_length=1, max_length=80)
    rank: int = Field(..., ge=1, le=10, description="1 represents highest urgency.")
    description: str = Field(..., min_length=5, max_length=400)
    response_target: str = Field(..., min_length=2, max_length=120)


class TeamConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    name: str = Field(..., min_length=1, max_length=120)
    responsibilities: str = Field(..., min_length=5, max_length=400)
    is_triage_fallback: bool = Field(default=False)


class RoutingRuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_id: str
    team_id: str
    fallback_team_id: str | None = None
    notes: str | None = None


class PriorityCriterionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    priority_id: str
    description: str
    signal_patterns: list[str] = Field(default_factory=list)

    @field_validator("signal_patterns")
    @classmethod
    def validate_regex_patterns(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Invalid regex pattern '{pattern}': {exc}") from exc
        return patterns


class SafetyCriterionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., min_length=1, max_length=64)
    label: str = Field(..., min_length=3, max_length=120)
    severity: Literal["critical", "high", "elevated"]
    minimum_priority_id: str
    patterns: list[str] = Field(..., min_length=1)
    recommended_action: str = Field(..., min_length=5, max_length=400)
    require_human_review: bool = Field(default=True)

    @field_validator("patterns")
    @classmethod
    def validate_regex_patterns(cls, patterns: list[str]) -> list[str]:
        for pattern in patterns:
            try:
                re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"Invalid safety regex pattern '{pattern}': {exc}") from exc
        return patterns

    @model_validator(mode="after")
    def safety_cannot_disable_review(self) -> SafetyCriterionConfig:
        if self.severity in ("critical", "high") and not self.require_human_review:
            raise ValueError(
                f"Safety criterion '{self.id}' with severity '{self.severity}' must set require_human_review=true."
            )
        return self


class HumanReviewRulesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    always_review_priority_ids: list[str] = Field(default_factory=list)
    review_on_safety_escalation: Literal[True] = True
    review_on_missing_critical_info: bool = True
    review_on_multi_category_ambiguity: bool = True
    review_on_unverified_evidence: Literal[True] = True


class ConfidenceThresholdsConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    abstention_threshold: float = Field(default=0.35, ge=0.05, le=0.90)
    human_review_threshold: float = Field(default=0.72, ge=0.10, le=0.95)
    high_confidence_threshold: float = Field(default=0.85, ge=0.20, le=0.99)

    @model_validator(mode="after")
    def validate_ordered_thresholds(self) -> ConfidenceThresholdsConfig:
        if not (self.abstention_threshold < self.human_review_threshold < self.high_confidence_threshold):
            raise ValueError(
                "Thresholds must satisfy abstention_threshold < human_review_threshold < high_confidence_threshold."
            )
        return self


class OrganisationalTriageConfig(BaseModel):
    """
    Authorised organisational configuration loaded from YAML or JSON.

    Cross-reference validation enforces referential integrity across categories,
    priorities, teams, routing rules, safety criteria, and thresholds.
    """

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    organisation_name: str = Field(..., min_length=2, max_length=140)
    domain_description: str = Field(..., min_length=10, max_length=600)
    ai_settings: AISettingsConfig = Field(default_factory=AISettingsConfig)
    categories: list[CategoryConfig] = Field(..., min_length=1)
    priorities: list[PriorityLevelConfig] = Field(..., min_length=2)
    teams: list[TeamConfig] = Field(..., min_length=1)
    routing_rules: list[RoutingRuleConfig] = Field(..., min_length=1)
    priority_criteria: list[PriorityCriterionConfig] = Field(default_factory=list)
    safety_criteria: list[SafetyCriterionConfig] = Field(default_factory=list)
    human_review_rules: HumanReviewRulesConfig = Field(default_factory=HumanReviewRulesConfig)
    confidence_thresholds: ConfidenceThresholdsConfig = Field(default_factory=ConfidenceThresholdsConfig)
    default_fallback_team_id: str | None = None
    allow_ai_team_routing_when_unmapped: bool = False

    @model_validator(mode="after")
    def validate_cross_references(self) -> OrganisationalTriageConfig:
        category_ids = [c.id for c in self.categories]
        if len(set(category_ids)) != len(category_ids):
            raise ValueError("Duplicate category id detected in categories.")
        category_set = set(category_ids)

        priority_ids = [p.id for p in self.priorities]
        if len(set(priority_ids)) != len(priority_ids):
            raise ValueError("Duplicate priority id detected in priorities.")
        priority_ranks = [p.rank for p in self.priorities]
        if len(set(priority_ranks)) != len(priority_ranks):
            raise ValueError("Priority ranks must be unique so urgency ordering is unambiguous.")
        priority_by_id = {p.id: p for p in self.priorities}

        team_ids = [t.id for t in self.teams]
        if len(set(team_ids)) != len(team_ids):
            raise ValueError("Duplicate team id detected in teams.")
        team_set = set(team_ids)

        if self.default_fallback_team_id is not None and self.default_fallback_team_id not in team_set:
            raise ValueError(
                f"default_fallback_team_id '{self.default_fallback_team_id}' does not match any configured team."
            )

        routed_categories: set[str] = set()
        for rule in self.routing_rules:
            if rule.category_id not in category_set:
                raise ValueError(
                    f"Routing rule references unknown category_id '{rule.category_id}'."
                )
            if rule.team_id not in team_set:
                raise ValueError(
                    f"Routing rule for category '{rule.category_id}' references unknown team_id '{rule.team_id}'."
                )
            if rule.fallback_team_id is not None and rule.fallback_team_id not in team_set:
                raise ValueError(
                    f"Routing rule for category '{rule.category_id}' references unknown fallback_team_id '{rule.fallback_team_id}'."
                )
            if rule.category_id in routed_categories:
                raise ValueError(
                    f"Contradictory routing rules: multiple routing rules defined for category '{rule.category_id}'."
                )
            routed_categories.add(rule.category_id)

        unrouted = category_set - routed_categories
        if unrouted and not (self.default_fallback_team_id or self.allow_ai_team_routing_when_unmapped):
            raise ValueError(
                f"Categories {sorted(unrouted)} have no routing rule and neither default_fallback_team_id "
                f"nor allow_ai_team_routing_when_unmapped is configured."
            )

        criterion_ids = [pc.id for pc in self.priority_criteria]
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("Duplicate id detected in priority_criteria.")
        for pc in self.priority_criteria:
            if pc.priority_id not in priority_by_id:
                raise ValueError(
                    f"Priority criterion '{pc.id}' references undefined priority_id '{pc.priority_id}'."
                )

        safety_ids = [sc.id for sc in self.safety_criteria]
        if len(set(safety_ids)) != len(safety_ids):
            raise ValueError("Duplicate id detected in safety_criteria.")
        highest_rank = min(p.rank for p in self.priorities)
        for sc in self.safety_criteria:
            if sc.minimum_priority_id not in priority_by_id:
                raise ValueError(
                    f"Safety criterion '{sc.id}' references undefined minimum_priority_id '{sc.minimum_priority_id}'."
                )
            if sc.severity == "critical" and priority_by_id[sc.minimum_priority_id].rank != highest_rank:
                raise ValueError(
                    f"Critical safety criterion '{sc.id}' must enforce the highest-urgency priority (rank {highest_rank})."
                )

        for pid in self.human_review_rules.always_review_priority_ids:
            if pid not in priority_by_id:
                raise ValueError(
                    f"human_review_rules.always_review_priority_ids references undefined priority_id '{pid}'."
                )

        return self

    def highest_priority(self) -> PriorityLevelConfig:
        return min(self.priorities, key=lambda p: p.rank)

    def priority_by_id(self, priority_id: str) -> PriorityLevelConfig | None:
        for p in self.priorities:
            if p.id == priority_id:
                return p
        return None

    def category_by_id(self, category_id: str) -> CategoryConfig | None:
        for c in self.categories:
            if c.id == category_id:
                return c
        return None

    def team_by_id(self, team_id: str) -> TeamConfig | None:
        for t in self.teams:
            if t.id == team_id:
                return t
        return None

    def routing_for_category(self, category_id: str) -> RoutingRuleConfig | None:
        for r in self.routing_rules:
            if r.category_id == category_id:
                return r
        return None
