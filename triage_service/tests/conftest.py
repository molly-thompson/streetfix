"""Shared fixtures and offline scripted AI provider for pytest evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import pytest

from triage_engine.config_loader import ConfigRegistry, EffectiveTriagePolicy
from triage_engine.providers.base import TriageAIProvider
from triage_engine.schemas import (
    AIAlternativeCategory,
    AIExtractedExcerpt,
    AIInferredItem,
    AIMissingInfoItem,
    AISafetyFlag,
    AITriageRawOutput,
    DecisionUncertaintyLevel,
    EvidenceQualityLevel,
    MaterialImpact,
    QualitativeConfidence,
    TriageRequest,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"


class ScriptedAIProvider(TriageAIProvider):
    """Deterministic test double implementing TriageAIProvider for offline tests."""

    provider_name = "scripted_test_provider"

    def __init__(
        self,
        handler: Callable[[TriageRequest, EffectiveTriagePolicy], AITriageRawOutput] | None = None,
    ) -> None:
        self._handler = handler

    def analyze_report(
        self,
        request: TriageRequest,
        policy: EffectiveTriagePolicy,
    ) -> AITriageRawOutput:
        if self._handler is not None:
            return self._handler(request, policy)

        profile = policy.org_config.profile_id
        desc = request.description
        snippet = desc[: min(len(desc), 60)]

        if "ceiling" in desc.lower() and "socket" in desc.lower():
            if profile == "campus_facilities":
                return AITriageRawOutput(
                    suggested_category_id="electrical_power",
                    alternative_category_ids=[
                        AIAlternativeCategory(
                            category_id="plumbing_water_ingress",
                            plausibility_note="Ceiling water ingress also implicates building plumbing.",
                        )
                    ],
                    suggested_priority_id="C2",
                    priority_rationale="Active water leak near campus electrical outlet.",
                    suggested_team_id="campus_mep_electrical",
                    routing_rationale="Campus electrical power category routes to Campus MEP.",
                    reported_facts=["Water is leaking through the ceiling near an electrical socket."],
                    evidence_excerpts=[
                        AIExtractedExcerpt(
                            quote="Water leaking through the ceiling near an electrical socket",
                            supports=["category", "safety"],
                        )
                    ],
                    inferred_conclusions=[
                        AIInferredItem(
                            conclusion="Moisture ingress may reach live electrical circuit.",
                            basis="Proximity of ceiling leak to wall socket.",
                        )
                    ],
                    reasoning_summary="Report describes ceiling water ingress adjacent to a campus electrical socket.",
                    ai_safety_flags=[
                        AISafetyFlag(
                            label="Electrical water contact risk",
                            severity="critical",
                            matched_text="electrical socket",
                            rationale="Water near live electrical outlet poses electrocution/fire risk.",
                        )
                    ],
                    missing_information=[
                        AIMissingInfoItem(
                            field="room_number",
                            question="Which room or circuit breaker serves this corridor?",
                            reason="Needed for immediate electrical isolation.",
                            material_impact=MaterialImpact.HIGH,
                        )
                    ],
                    model_qualitative_confidence=QualitativeConfidence.HIGH,
                    model_uncalibrated_estimate=0.89,
                    evidence_quality=EvidenceQualityLevel.SUFFICIENT,
                    evidence_quality_explanation="Clear description of defect and hazard proximity.",
                    decision_uncertainty=DecisionUncertaintyLevel.MODERATE,
                    decision_uncertainty_explanation="Dual-trade overlap between electrical and plumbing.",
                    recommend_human_review=True,
                    human_review_reasons=["Dual-trade electrical and plumbing hazard."],
                )

            return AITriageRawOutput(
                suggested_category_id="building_internal_adjacent",
                alternative_category_ids=[
                    AIAlternativeCategory(
                        category_id="street_lighting",
                        plausibility_note="Electrical hazard may require highway/public electrical support.",
                    )
                ],
                suggested_priority_id="P2",
                priority_rationale="Water ingress near socket inside council building.",
                suggested_team_id="civic_assets_team",
                routing_rationale="Council building defects route to Civic Assets Team.",
                reported_facts=["Water is leaking through the ceiling near an electrical socket."],
                evidence_excerpts=[
                    AIExtractedExcerpt(
                        quote="Water leaking through the ceiling near an electrical socket",
                        supports=["category", "safety"],
                    )
                ],
                inferred_conclusions=[
                    AIInferredItem(
                        conclusion="Potential risk of short circuit inside civic asset.",
                        basis="Water leaking near electrical socket.",
                    )
                ],
                reasoning_summary="Internal building water leak near electrical socket.",
                ai_safety_flags=[],
                missing_information=[
                    AIMissingInfoItem(
                        field="building_name",
                        question="Which council building is affected?",
                        reason="Required to dispatch Civic Assets & Electrical engineer.",
                        material_impact=MaterialImpact.HIGH,
                    )
                ],
                model_qualitative_confidence=QualitativeConfidence.MEDIUM,
                model_uncalibrated_estimate=0.78,
                evidence_quality=EvidenceQualityLevel.PARTIAL,
                evidence_quality_explanation="Hazard is clear; specific building name not yet confirmed.",
                decision_uncertainty=DecisionUncertaintyLevel.MODERATE,
                decision_uncertainty_explanation="Both civic building and electrical teams may be involved.",
                recommend_human_review=True,
                human_review_reasons=["High-risk electrical/water interaction."],
            )

        # Default clear response using first category & mid-priority
        first_cat = policy.org_config.categories[0].id
        lowest_p = sorted(policy.org_config.priorities, key=lambda p: p.rank)[-1].id
        return AITriageRawOutput(
            suggested_category_id=first_cat,
            suggested_priority_id=lowest_p,
            priority_rationale="Routine issue unless overridden by deterministic safety rules.",
            routing_rationale="Mapped via configured routing table.",
            reported_facts=[desc],
            evidence_excerpts=[AIExtractedExcerpt(quote=snippet, supports=["category"])],
            inferred_conclusions=[
                AIInferredItem(conclusion="Appears consistent with primary category.", basis="Description text.")
            ],
            reasoning_summary="Standard structured triage interpretation.",
            model_qualitative_confidence=QualitativeConfidence.HIGH,
            model_uncalibrated_estimate=0.91,
            evidence_quality=EvidenceQualityLevel.SUFFICIENT,
            evidence_quality_explanation="Sufficient detail provided.",
            decision_uncertainty=DecisionUncertaintyLevel.LOW,
            decision_uncertainty_explanation="Single clear category.",
            recommend_human_review=False,
        )


@pytest.fixture
def config_registry() -> ConfigRegistry:
    return ConfigRegistry.from_directory(CONFIG_DIR)
