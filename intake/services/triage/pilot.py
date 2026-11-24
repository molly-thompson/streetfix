"""Summarize shadow-rule results against recorded human decisions."""

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError

from intake.models import TriageAttempt


@dataclass(frozen=True)
class FieldMetrics:
    """Counts for one proposed decision field."""

    determined: int
    ambiguous: int
    conflicting: int
    agreed: int
    disagreed: int
    high_risk_missed: int
    high_risk_undetermined: int


@dataclass(frozen=True)
class PilotSummary:
    """Aggregate shadow results; this never approves automation."""

    proposals: int
    reviewed_acceptances: int
    priority: FieldMetrics
    urgency: FieldMetrics


def summarize_pilot(policy_version: str) -> PilotSummary:
    """Compare the latest rules proposal per report with a human acceptance."""
    if not policy_version.strip():
        raise ValidationError("A policy version is required.")
    proposals: dict[int, dict[str, Any]] = {}
    matching = TriageAttempt.objects.filter(
        stage=TriageAttempt.Stage.RULES,
        decision="PROPOSED",
        policy_version=policy_version,
    )
    attempts = matching.order_by("submission_id", "created_at", "pk").values_list(
        "submission_id", "field_outcomes"
    )
    for submission_id, outcomes in attempts:
        if isinstance(outcomes, dict):
            proposals[submission_id] = outcomes
    acceptances: dict[int, dict[str, Any]] = {}
    accepted_attempts = (
        TriageAttempt.objects.filter(
            submission_id__in=matching.values("submission_id"),
            stage=TriageAttempt.Stage.HUMAN,
            decision="ACCEPTED",
        )
        .order_by("submission_id", "created_at", "pk")
        .values_list("submission_id", "field_outcomes")
    )
    for submission_id, outcomes in accepted_attempts:
        if isinstance(outcomes, dict):
            acceptances[submission_id] = outcomes

    def field_metrics(field: str) -> FieldMetrics:
        determined = ambiguous = conflicting = agreed = disagreed = 0
        high_risk_missed = high_risk_undetermined = 0
        high_risk_code = "CRITICAL" if field == "priority" else "EMERGENCY"
        for submission_id, outcomes in proposals.items():
            proposed = outcomes.get(field)
            if not isinstance(proposed, dict):
                continue
            state = proposed.get("state")
            human = acceptances.get(submission_id, {}).get(field)
            if state == "determined" and proposed.get("value"):
                determined += 1
                if human:
                    if human == proposed["value"]:
                        agreed += 1
                    else:
                        disagreed += 1
                        if human == high_risk_code:
                            high_risk_missed += 1
            elif state == "ambiguous":
                ambiguous += 1
                if human == high_risk_code:
                    high_risk_undetermined += 1
            elif state == "conflicting":
                conflicting += 1
                if human == high_risk_code:
                    high_risk_undetermined += 1
        return FieldMetrics(
            determined,
            ambiguous,
            conflicting,
            agreed,
            disagreed,
            high_risk_missed,
            high_risk_undetermined,
        )

    return PilotSummary(
        proposals=len(proposals),
        reviewed_acceptances=len(acceptances),
        priority=field_metrics("priority"),
        urgency=field_metrics("urgency"),
    )
