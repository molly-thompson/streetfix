"""Tests for independent, negation-aware deterministic safety evaluation."""

from __future__ import annotations

from tests.conftest import ScriptedAIProvider
from triage_engine.config_loader import ConfigRegistry
from triage_engine.safety import SafetyEvaluator
from triage_engine.schemas import AITriageRawOutput, QualitativeConfidence, EvidenceQualityLevel, DecisionUncertaintyLevel, TriageRequest
from triage_engine.service import TriageService


def test_explicit_electrical_water_hazard_detected(config_registry: ConfigRegistry) -> None:
    evaluator = SafetyEvaluator()
    cfg = config_registry.get("streetfix")
    outcome = evaluator.evaluate("Water leaking through the ceiling near an electrical socket.", cfg)
    assert outcome.assessment.escalation_triggered is True
    assert any(h.hazard_id == "SYS_ELECTRICAL_WATER_HAZARD" for h in outcome.assessment.matched_hazards)
    assert outcome.enforced_min_priority_rank == 1
    assert outcome.requires_human_review is True


def test_negated_hazard_does_not_false_escalate(config_registry: ConfigRegistry) -> None:
    evaluator = SafetyEvaluator()
    cfg = config_registry.get("streetfix")
    outcome = evaluator.evaluate(
        "Large rainwater puddle on footpath. Inspected closely and confirmed no live wires or sparking equipment nearby.",
        cfg,
    )
    assert outcome.assessment.escalation_triggered is False
    assert len(outcome.assessment.matched_hazards) == 0
    assert any(m.assessment == "negated" for m in outcome.assessment.negated_or_uncertain_mentions)


def test_uncertain_hazard_wording_triggers_human_review(config_registry: ConfigRegistry) -> None:
    evaluator = SafetyEvaluator()
    cfg = config_registry.get("streetfix")
    outcome = evaluator.evaluate(
        "Water pooling next to streetlamp base; unsure if there might be exposed live wires inside.",
        cfg,
    )
    assert outcome.requires_human_review is True
    assert any(
        m.assessment == "uncertain_or_contradictory"
        for m in outcome.assessment.negated_or_uncertain_mentions
    )


def test_contradictory_hazard_details_flagged_for_review(config_registry: ConfigRegistry) -> None:
    evaluator = SafetyEvaluator()
    cfg = config_registry.get("streetfix")
    outcome = evaluator.evaluate(
        "Heavy flooding blocking the pedestrian underpass. Actually completely dry now with no water visible.",
        cfg,
    )
    assert len(outcome.contradictions_detected) >= 1
    assert outcome.requires_human_review is True


def test_multiple_simultaneous_hazards_all_captured(config_registry: ConfigRegistry) -> None:
    evaluator = SafetyEvaluator()
    cfg = config_registry.get("streetfix")
    outcome = evaluator.evaluate(
        "Strong smell of gas near a missing manhole cover while sparking wires hang over the pavement.",
        cfg,
    )
    ids = {h.hazard_id for h in outcome.assessment.matched_hazards}
    assert {"SYS_GAS_EXPLOSION_HAZARD", "SYS_TRAFFIC_LIFE_SAFETY", "SYS_ELECTRICAL_WATER_HAZARD"}.issubset(ids)
    assert outcome.enforced_min_priority_rank == 1


def test_high_confidence_ai_low_priority_cannot_downgrade_safety(config_registry: ConfigRegistry) -> None:
    def low_priority_high_conf_ai(_req, _policy) -> AITriageRawOutput:
        return AITriageRawOutput(
            suggested_category_id="street_lighting",
            suggested_priority_id="P4",
            priority_rationale="Cosmetic column door issue.",
            routing_rationale="Street lighting team.",
            reported_facts=["Exposed wires are sparking in puddle."],
            evidence_excerpts=[],
            inferred_conclusions=[],
            reasoning_summary="Low priority assessment by AI.",
            model_qualitative_confidence=QualitativeConfidence.HIGH,
            model_uncalibrated_estimate=0.98,
            evidence_quality=EvidenceQualityLevel.SUFFICIENT,
            evidence_quality_explanation="Clear description.",
            decision_uncertainty=DecisionUncertaintyLevel.LOW,
            decision_uncertainty_explanation="Unambiguous.",
            recommend_human_review=False,
        )

    service = TriageService(config_registry, ScriptedAIProvider(handler=low_priority_high_conf_ai))
    res = service.triage(
        TriageRequest(
            description="Exposed wires are sparking in the rain puddle outside Oakwood Primary.",
            profile_id="streetfix",
        )
    )
    assert res.safety_assessment.escalation_triggered is True
    assert res.priority_recommendation.priority_id == "P1"
    assert res.priority_recommendation.escalated_by_safety is True
    assert res.human_review.required is True
    assert "SAFETY_PRIORITY_OVERRIDE" in res.deterministic_rules_triggered
