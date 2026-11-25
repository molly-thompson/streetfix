"""Tests for verifiable evidence attribution and unsupported/hallucinated quote detection."""

from __future__ import annotations

from tests.conftest import ScriptedAIProvider
from triage_engine.config_loader import ConfigRegistry
from triage_engine.schemas import (
    AIExtractedExcerpt,
    AIInferredItem,
    AITriageRawOutput,
    DecisionUncertaintyLevel,
    EvidenceQualityLevel,
    QualitativeConfidence,
    TriageRequest,
)
from triage_engine.service import TriageService


def test_verifies_exact_quotes_and_flags_fabricated_excerpts(config_registry: ConfigRegistry) -> None:
    def ai_with_fabricated_quote(_req, _policy) -> AITriageRawOutput:
        return AITriageRawOutput(
            suggested_category_id="potholes_roads",
            suggested_priority_id="P3",
            priority_rationale="Standard pothole.",
            routing_rationale="Highways.",
            reported_facts=["Deep pothole on High Street."],
            evidence_excerpts=[
                AIExtractedExcerpt(
                    quote="deep pothole on High Street",
                    supports=["category"],
                ),
                AIExtractedExcerpt(
                    quote="three ambulances were called to the scene",
                    supports=["priority"],
                ),
            ],
            inferred_conclusions=[
                AIInferredItem(
                    conclusion="May worsen during freeze-thaw cycles.",
                    basis="Reported tarmac defect.",
                )
            ],
            reasoning_summary="Verified and unverified excerpt test.",
            model_qualitative_confidence=QualitativeConfidence.HIGH,
            model_uncalibrated_estimate=0.88,
            evidence_quality=EvidenceQualityLevel.SUFFICIENT,
            evidence_quality_explanation="Clear.",
            decision_uncertainty=DecisionUncertaintyLevel.LOW,
            decision_uncertainty_explanation="Clear.",
            recommend_human_review=False,
        )

    service = TriageService(config_registry, ScriptedAIProvider(handler=ai_with_fabricated_quote))
    res = service.triage(
        TriageRequest(
            description="There is a deep pothole on High Street near the bakery.",
            profile_id="streetfix",
        )
    )
    excerpts = res.evidence_and_reasoning.evidence_excerpts
    assert len(excerpts) == 2
    assert excerpts[0].verified_in_source is True
    assert excerpts[1].verified_in_source is False
    assert excerpts[1].verification_note is not None
    assert any("Unverified evidence excerpt" in f for f in res.evidence_and_reasoning.unsupported_or_contradictory_flags)
    assert res.human_review.required is True
    assert all(inf.explicitly_inferred is True for inf in res.evidence_and_reasoning.inferred_conclusions)
