from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AnalysisMode = Literal["hybrid", "deterministic"]
SignalKey = Literal["semantic", "geographical", "temporal", "categorical", "contextual"]
SignalStatus = Literal["evaluated", "partial", "missing"]
MatchClassification = Literal[
    "likely_duplicate", "related_reports", "similar_but_unrelated", "unrelated"
]
ReviewRecommendation = Literal[
    "review_together", "link_as_related", "monitor_recurring", "no_action"
]
ConfidenceBand = Literal["high", "medium", "low"]
HumanReviewAction = Literal["confirm_duplicate", "link_related", "reject_match"]


class ReportLocation(BaseModel):
    latitude: float | None = None
    longitude: float | None = None
    address: str | None = None
    locationDescription: str | None = None
    zone: str | None = None
    postcode: str | None = None


class GenericReport(BaseModel):
    id: str = Field(..., min_length=1)
    title: str | None = None
    description: str = Field(..., min_length=3)
    category: str | None = None
    subcategory: str | None = None
    location: ReportLocation | None = None
    reportedAt: str | None = None
    status: str | None = None
    source: str | None = None
    metadata: dict[str, Any] | None = None


class SignalWeights(BaseModel):
    semantic: float = Field(0.34, ge=0.0, le=1.0)
    geographical: float = Field(0.30, ge=0.0, le=1.0)
    temporal: float = Field(0.14, ge=0.0, le=1.0)
    categorical: float = Field(0.12, ge=0.0, le=1.0)
    contextual: float = Field(0.10, ge=0.0, le=1.0)


class MatchingThresholds(BaseModel):
    likelyDuplicateScore: float = Field(0.72, ge=0.0, le=1.0)
    relatedReportScore: float = Field(0.50, ge=0.0, le=1.0)
    similarUnrelatedSemanticMin: float = Field(0.55, ge=0.0, le=1.0)
    semanticDuplicateThreshold: float = Field(0.52, ge=0.0, le=1.0)
    maxDuplicateDistanceMeters: float = Field(85.0, gt=0.0)
    relatedDistanceMeters: float = Field(250.0, gt=0.0)
    duplicateTimeWindowHours: float = Field(168.0, gt=0.0)
    recurringMinGapHours: float = Field(720.0, gt=0.0)
    minimumSignalsAvailable: int = Field(2, ge=1, le=5)


class CategoryRules(BaseModel):
    relatedGroups: list[list[str]] = Field(default_factory=list)
    incompatibleGroups: list[list[str]] = Field(default_factory=list)
    treatSameCategoryBonus: float = Field(0.04, ge=0.0, le=0.5)
    crossCategoryAllowed: bool = True


class MatchingConfig(BaseModel):
    presetId: str = "generic"
    presetName: str = "Deployment policy"
    sector: str = "Public services"
    mode: AnalysisMode = "deterministic"
    weights: SignalWeights = Field(
        default_factory=lambda: SignalWeights.model_validate({})
    )
    thresholds: MatchingThresholds = Field(
        default_factory=lambda: MatchingThresholds.model_validate({})
    )
    categoryRules: CategoryRules = Field(
        default_factory=lambda: CategoryRules.model_validate({})
    )


class PartialMatchingConfig(BaseModel):
    presetId: str | None = None
    mode: AnalysisMode | None = None
    weights: dict[str, float] | None = None
    thresholds: dict[str, Any] | None = None
    categoryRules: dict[str, Any] | None = None


class CategoryOption(BaseModel):
    id: str
    label: str


class OrganisationalPreset(BaseModel):
    id: str
    name: str
    sector: str
    description: str
    categories: list[CategoryOption]
    config: MatchingConfig


class SignalAssessment(BaseModel):
    key: SignalKey
    label: str
    score: float | None = None
    weight: float
    effectiveWeight: float
    weightedContribution: float
    status: SignalStatus
    summary: str
    evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)


class MatchAssessment(BaseModel):
    candidateReportId: str
    candidateReport: GenericReport
    classification: MatchClassification
    classificationLabel: str
    compositeScore: float
    scoreIsAdvisory: bool = True
    confidenceBand: ConfidenceBand
    recommendation: ReviewRecommendation
    recommendationLabel: str
    signalBreakdown: dict[SignalKey, SignalAssessment]
    signalsAvailableCount: int
    similarities: list[str]
    differences: list[str]
    contradictions: list[str]
    uncertaintyNotes: list[str]
    explanation: str
    semanticSource: Literal["gemini_hybrid", "deterministic"]


class IncomingReportSummary(BaseModel):
    id: str
    availableSignals: list[SignalKey]
    missingFields: list[str]
    completenessRatio: float


class SummaryStats(BaseModel):
    totalCandidates: int
    likelyDuplicates: int
    relatedReports: int
    similarButUnrelated: int
    unrelated: int
    highestCompositeScore: float


class DuplicateDetectionRequest(BaseModel):
    incomingReport: GenericReport
    existingReports: list[GenericReport]
    presetId: str | None = None
    config: PartialMatchingConfig | None = None


class DuplicateDetectionResponse(BaseModel):
    requestId: str
    processedAt: str
    engineVersion: str = "1.0.0"
    advisoryNotice: str
    effectiveConfig: MatchingConfig
    incomingReportSummary: IncomingReportSummary
    summaryStats: SummaryStats
    assessments: list[MatchAssessment]
