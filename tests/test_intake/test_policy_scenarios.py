"""Tests for staff-authored policy examples."""

import pytest
from django.core.exceptions import ValidationError

from intake.models import TriagePolicy, TriagePolicyRule, TriagePolicyScenario
from intake.services.triage.scenarios import evaluate_scenarios

pytestmark = pytest.mark.django_db


def test_scenario_validates_each_expected_outcome() -> None:
    """Only determined fields have a valid priority or urgency code."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    scenario = TriagePolicyScenario(
        policy=policy,
        name="High impact",
        impact="SIGNIFICANT",
        priority_state="determined",
        priority_code="HIGH",
        urgency_state="ambiguous",
        urgency_code="",
    )
    scenario.full_clean()
    scenario.priority_code = ""
    scenario.urgency_code = "URGENT"
    with pytest.raises(ValidationError) as error:
        scenario.full_clean()
    assert set(error.value.message_dict) == {"priority_code", "urgency_code"}


def test_scenario_rejects_sensitive_evidence_without_relevant_issue() -> None:
    """Examples cannot use an issue-specific modifier on unrelated issues."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    scenario = TriagePolicyScenario(
        policy=policy,
        name="Sensitive",
        sensitive_content="YES",
        priority_state="ambiguous",
        urgency_state="ambiguous",
    )
    with pytest.raises(ValidationError) as error:
        scenario.full_clean()
    assert "sensitive_content" in error.value.message_dict


def test_scenario_evaluation_detects_regressions_and_abstention() -> None:
    """Examples report actual outcomes without changing policy state."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    TriagePolicyRule.objects.create(
        policy=policy,
        name="High impact",
        impact="SIGNIFICANT",
        target="PRIORITY",
        outcome_code="HIGH",
    )
    TriagePolicyScenario.objects.create(
        policy=policy,
        name="Significant",
        impact="SIGNIFICANT",
        priority_state="determined",
        priority_code="HIGH",
        urgency_state="ambiguous",
    )
    TriagePolicyScenario.objects.create(
        policy=policy,
        name="Uncertain evidence",
        impact="UNKNOWN",
        priority_state="determined",
        priority_code="LOW",
        urgency_state="ambiguous",
    )
    results = {result.name: result for result in evaluate_scenarios(policy)}
    assert results["Significant"].passed is True
    assert results["Uncertain evidence"].passed is False
    assert results["Uncertain evidence"].priority.state == "ambiguous"
    policy.refresh_from_db()
    assert policy.status == "DRAFT"


def test_scenario_evaluation_requires_examples_and_valid_rules() -> None:
    """Empty or invalid policies cannot pass example evaluation."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    with pytest.raises(ValidationError):
        evaluate_scenarios(policy)
    TriagePolicyRule.objects.create(
        policy=policy,
        name="Invalid",
        impact="INVALID",
        target="PRIORITY",
        outcome_code="HIGH",
    )
    TriagePolicyScenario.objects.create(
        policy=policy,
        name="Example",
        priority_state="ambiguous",
        urgency_state="ambiguous",
    )
    with pytest.raises(ValidationError):
        evaluate_scenarios(policy)
