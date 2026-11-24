"""Evaluate staff-authored examples against a policy draft."""

from dataclasses import dataclass

from django.core.exceptions import ValidationError

from intake.models import TriagePolicy, TriagePolicyRule
from intake.services.triage.results import Evidence, FieldOutcome
from intake.services.triage.rules import evaluate_field


@dataclass(frozen=True)
class ScenarioResult:
    """Actual results and whether they match an example's expectations."""

    scenario_id: int
    name: str
    priority: FieldOutcome
    urgency: FieldOutcome
    passed: bool


def evaluate_scenarios(policy: TriagePolicy) -> list[ScenarioResult]:
    """Check all configured examples without approving or activating a policy."""
    rules = list(policy.rules.select_related("issue_type"))
    scenarios = list(policy.scenarios.select_related("issue_type"))
    if not rules or not scenarios:
        raise ValidationError("A policy needs rules and examples before checking.")
    for rule in rules:
        rule.full_clean()
    results = []
    for scenario in scenarios:
        scenario.full_clean()
        evidence = Evidence(
            issue_type_id=scenario.issue_type_id,
            impact=scenario.impact,
            time_sensitivity=scenario.time_sensitivity,
            sensitive_content=scenario.sensitive_content,
        )
        priority = evaluate_field(
            rules, target=TriagePolicyRule.Target.PRIORITY, evidence=evidence
        )
        urgency = evaluate_field(
            rules, target=TriagePolicyRule.Target.URGENCY, evidence=evidence
        )
        results.append(
            ScenarioResult(
                scenario_id=scenario.pk,
                name=scenario.name,
                priority=priority,
                urgency=urgency,
                passed=(
                    priority.state == scenario.priority_state
                    and priority.value == (scenario.priority_code or None)
                    and urgency.state == scenario.urgency_state
                    and urgency.value == (scenario.urgency_code or None)
                ),
            )
        )
    return results
