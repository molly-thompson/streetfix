"""Tests for shadow-triage measurements."""

import pytest
from django.core.exceptions import ValidationError

from intake.models import ReportSubmission, TriageAttempt
from intake.services.triage.pilot import summarize_pilot

pytestmark = pytest.mark.django_db


def test_summary_compares_each_field_and_keeps_abstentions_visible() -> None:
    """Unreviewed proposals do not count as agreement or disagreement."""
    first = ReportSubmission.objects.create(description="One", updates_requested=False)
    second = ReportSubmission.objects.create(description="Two", updates_requested=False)
    TriageAttempt.objects.create(
        submission=first,
        stage="RULES",
        decision="PROPOSED",
        policy_version="1",
        field_outcomes={
            "priority": {"state": "determined", "value": "HIGH"},
            "urgency": {"state": "determined", "value": "URGENT"},
        },
    )
    TriageAttempt.objects.create(
        submission=first,
        stage="HUMAN",
        decision="ACCEPTED",
        field_outcomes={"priority": "HIGH", "urgency": "SOON"},
    )
    TriageAttempt.objects.create(
        submission=second,
        stage="RULES",
        decision="PROPOSED",
        policy_version="1",
        field_outcomes={
            "priority": {"state": "ambiguous", "value": None},
            "urgency": {"state": "conflicting", "value": None},
        },
    )
    summary = summarize_pilot("1")
    assert summary.proposals == 2
    assert summary.reviewed_acceptances == 1
    assert summary.priority.determined == 1
    assert summary.priority.ambiguous == 1
    assert summary.priority.agreed == 1
    assert summary.priority.disagreed == 0
    assert summary.urgency.conflicting == 1
    assert summary.urgency.disagreed == 1


def test_summary_uses_latest_proposal_per_report_and_exact_version() -> None:
    """Repeated evaluations do not inflate counts or mix policy versions."""
    submission = ReportSubmission.objects.create(
        description="One", updates_requested=False
    )
    for version, value in (("1", "LOW"), ("1", "HIGH"), ("2", "NORMAL")):
        TriageAttempt.objects.create(
            submission=submission,
            stage="RULES",
            decision="PROPOSED",
            policy_version=version,
            field_outcomes={"priority": {"state": "determined", "value": value}},
        )
    TriageAttempt.objects.create(
        submission=submission,
        stage="HUMAN",
        decision="ACCEPTED",
        field_outcomes={"priority": "HIGH"},
    )
    summary = summarize_pilot("1")
    assert summary.proposals == 1
    assert summary.priority.agreed == 1
    assert summary.priority.disagreed == 0
    with pytest.raises(ValidationError):
        summarize_pilot("")


def test_high_risk_outcomes_are_separated_from_abstentions() -> None:
    """Critical and emergency disagreements are not hidden in overall rates."""
    for priority_state in ("determined", "ambiguous"):
        submission = ReportSubmission.objects.create(
            description="A report", updates_requested=False
        )
        TriageAttempt.objects.create(
            submission=submission,
            stage="RULES",
            decision="PROPOSED",
            policy_version="1",
            field_outcomes={
                "priority": {
                    "state": priority_state,
                    "value": "HIGH" if priority_state == "determined" else None,
                },
                "urgency": {"state": "conflicting", "value": None},
            },
        )
        TriageAttempt.objects.create(
            submission=submission,
            stage="HUMAN",
            decision="ACCEPTED",
            field_outcomes={"priority": "CRITICAL", "urgency": "EMERGENCY"},
        )
    summary = summarize_pilot("1")
    assert summary.priority.high_risk_missed == 1
    assert summary.priority.high_risk_undetermined == 1
    assert summary.urgency.high_risk_missed == 0
    assert summary.urgency.high_risk_undetermined == 2
