"""Tests for deterministic policy matching."""

from intake.models import TriagePolicyRule
from intake.services.triage.results import Evidence, OutcomeState
from intake.services.triage.rules import evaluate_field


def rule(pk: int, impact: str, outcome: str, *, time: str = "") -> TriagePolicyRule:
    """Construct a policy rule without needing persisted configuration."""
    return TriagePolicyRule(
        pk=pk,
        target=TriagePolicyRule.Target.PRIORITY,
        impact=impact,
        time_sensitivity=time,
        outcome_code=outcome,
    )


def test_unambiguous_match_returns_a_proposal_with_rule_evidence() -> None:
    """A single matching policy outcome is explainable."""
    result = evaluate_field(
        [rule(1, "SIGNIFICANT", "HIGH"), rule(2, "LIMITED", "LOW")],
        target=TriagePolicyRule.Target.PRIORITY,
        evidence=Evidence(impact="SIGNIFICANT"),
    )
    assert result.state == OutcomeState.DETERMINED
    assert result.value == "HIGH"
    assert result.matched_rule_ids == (1,)


def test_missing_input_abstains_when_another_rule_could_match() -> None:
    """Unknown evidence must not incorrectly rule out a competing rule."""
    result = evaluate_field(
        [
            rule(1, "SIGNIFICANT", "HIGH"),
            rule(2, "SIGNIFICANT", "CRITICAL", time="IMMEDIATE"),
        ],
        target=TriagePolicyRule.Target.PRIORITY,
        evidence=Evidence(impact="SIGNIFICANT"),
    )
    assert result.state == OutcomeState.AMBIGUOUS
    assert result.value is None


def test_conflicting_matches_abstain_instead_of_choosing_one() -> None:
    """Conflicting configured rules do not silently select a priority."""
    result = evaluate_field(
        [rule(1, "SIGNIFICANT", "HIGH"), rule(2, "SIGNIFICANT", "CRITICAL")],
        target=TriagePolicyRule.Target.PRIORITY,
        evidence=Evidence(impact="SIGNIFICANT"),
    )
    assert result.state == OutcomeState.CONFLICTING
    assert result.value is None
    assert result.matched_rule_ids == (1, 2)


def test_no_matching_rules_abstains() -> None:
    """The absence of a match is not a low-risk classification."""
    result = evaluate_field(
        [rule(1, "LIMITED", "LOW")],
        target=TriagePolicyRule.Target.PRIORITY,
        evidence=Evidence(impact="SEVERE"),
    )
    assert result.state == OutcomeState.AMBIGUOUS
    assert result.value is None


def test_priority_and_urgency_are_evaluated_independently() -> None:
    """Uncertainty in one dimension does not invent an outcome for another."""
    priority = rule(1, "SIGNIFICANT", "HIGH")
    urgency = TriagePolicyRule(
        pk=2,
        target=TriagePolicyRule.Target.URGENCY,
        time_sensitivity="IMMEDIATE",
        outcome_code="EMERGENCY",
    )
    evidence = Evidence(impact="SIGNIFICANT")
    rules = [priority, urgency]
    assert (
        evaluate_field(rules, target="PRIORITY", evidence=evidence).state
        == OutcomeState.DETERMINED
    )
    assert (
        evaluate_field(rules, target="URGENCY", evidence=evidence).state
        == OutcomeState.AMBIGUOUS
    )
