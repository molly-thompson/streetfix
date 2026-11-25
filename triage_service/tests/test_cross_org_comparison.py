"""Tests for side-by-side cross-organisation comparison and safety consistency."""

from __future__ import annotations

from tests.conftest import ScriptedAIProvider
from triage_engine.config_loader import ConfigRegistry
from triage_engine.schemas import LocationInput, SharedReportInput, TriageCompareRequest
from triage_engine.service import TriageService


def test_cross_org_comparison_shares_safety_escalation_while_routing_differently(
    config_registry: ConfigRegistry,
) -> None:
    service = TriageService(config_registry, ScriptedAIProvider())
    req = TriageCompareRequest(
        report=SharedReportInput(
            description="Water leaking through the ceiling near an electrical socket.",
            location=LocationInput(free_text="Ground floor corridor beside main stairwell"),
        ),
        profile_ids=["streetfix", "campus_facilities"],
    )

    cmp_res = service.compare(req)
    assert cmp_res.safety_consistency_verified is True

    sf = cmp_res.results_by_profile["streetfix"]
    cf = cmp_res.results_by_profile["campus_facilities"]

    # Both organisations enforce mandatory electrical-water safety escalation and human review
    assert sf.safety_assessment.escalation_triggered is True
    assert cf.safety_assessment.escalation_triggered is True
    assert sf.human_review.required is True
    assert cf.human_review.required is True
    assert sf.priority_recommendation.priority_id == "P1"
    assert cf.priority_recommendation.priority_id == "C1"

    # Yet categories and responsible teams diverge per organisational configuration
    assert sf.category_recommendation.primary_category_id != cf.category_recommendation.primary_category_id
    assert sf.routing_recommendation.team_id != cf.routing_recommendation.team_id
    assert sf.routing_recommendation.team_id == "civic_assets_team"
    assert cf.routing_recommendation.team_id == "campus_mep_electrical"

    diff_map = {d.dimension: d for d in cmp_res.comparison_diffs}
    assert diff_map["category"].differs is True
    assert diff_map["team"].differs is True
    assert diff_map["safety_assessment"].differs is False
    assert "safety" in cmp_res.policy_explanation.lower()
