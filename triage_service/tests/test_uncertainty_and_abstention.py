"""Tests for separated confidence/uncertainty dimensions and abstention rules."""

from __future__ import annotations

from tests.conftest import ScriptedAIProvider
from triage_engine.config_loader import ConfigRegistry
from triage_engine.schemas import (
    AITriageRawOutput,
    DecisionUncertaintyLevel,
    EvidenceQualityLevel,
    QualitativeConfidence,
    RoutingSource,
    TriageRequest,
    TriageStatus,
)
from triage_engine.service import TriageService


def test_abstains_when_evidence_insufficient_or_below_threshold(config_registry: ConfigRegistry) -> None:
    def vague_ai(_req, _policy) -> AITriageRawOutput:
        return AITriageRawOutput(
            suggested_category_id="potholes_roads",
            suggested_priority_id="P3",
            priority_rationale="Insufficient information.",
            routing_rationale="Unclear.",
            reported_facts=["It's broken near the park, please fix ASAP."],
            evidence_excerpts=[],
            inferred_conclusions=[],
            reasoning_summary="Report does not specify what asset is broken or where.",
            model_qualitative_confidence=QualitativeConfidence.LOW,
            model_uncalibrated_estimate=0.25,
            evidence_quality=EvidenceQualityLevel.INSUFFICIENT,
            evidence_quality_explanation="Missing asset type and exact location.",
            decision_uncertainty=DecisionUncertaintyLevel.HIGH,
            decision_uncertainty_explanation="Could relate to benches, lighting, signage, or footpaths.",
            recommend_human_review=True,
            human_review_reasons=["Insufficient evidence for automated triage."],
        )

    service = TriageService(config_registry, ScriptedAIProvider(handler=vague_ai))
    res = service.triage(TriageRequest(description="It's broken near the park, please fix ASAP."))

    assert res.status == TriageStatus.ABSTAINED
    assert res.category_recommendation.abstained is True
    assert res.category_recommendation.primary_category_id is None
    assert "category" in res.uncertainty_assessment.abstained_dimensions
    assert res.routing_recommendation.routing_source == RoutingSource.UNASSIGNED_FOR_REVIEW
    assert res.routing_recommendation.team_id == "triage_duty_desk"
    assert res.human_review.required is True
    assert "uncalibrated" in res.uncertainty_assessment.model_self_assessment.calibration_disclaimer.lower()


def test_abstains_if_ai_hallucinates_unknown_category(config_registry: ConfigRegistry) -> None:
    def hallucinated_cat_ai(_req, _policy) -> AITriageRawOutput:
        return AITriageRawOutput(
            suggested_category_id="nonexistent_category_xyz",
            suggested_priority_id="P3",
            priority_rationale="Guessed.",
            routing_rationale="Guessed.",
            reported_facts=["Complaint text."],
            evidence_excerpts=[],
            inferred_conclusions=[],
            reasoning_summary="Hallucinated category.",
            model_qualitative_confidence=QualitativeConfidence.MEDIUM,
            model_uncalibrated_estimate=0.68,
            evidence_quality=EvidenceQualityLevel.PARTIAL,
            evidence_quality_explanation="Partial.",
            decision_uncertainty=DecisionUncertaintyLevel.MODERATE,
            decision_uncertainty_explanation="Uncertain.",
            recommend_human_review=False,
        )

    service = TriageService(config_registry, ScriptedAIProvider(handler=hallucinated_cat_ai))
    res = service.triage(TriageRequest(description="Unusual noise from private delivery vans at 4am."))
    assert res.status == TriageStatus.ABSTAINED
    assert res.category_recommendation.abstained is True
    assert res.human_review.required is True
