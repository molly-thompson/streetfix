"""Tests for coordinating deterministic triage."""

import pytest
from django.utils import timezone

from employees.organisation_models import Department, IssueType
from intake.models import ReportSubmission, TriagePolicy, TriagePolicyRule
from intake.services.triage.orchestrator import triage_submission
from intake.services.triage.taxonomy import snapshot_taxonomy

pytestmark = pytest.mark.django_db


def new_submission(**kwargs: object) -> ReportSubmission:
    """Create intake without operational work."""
    return ReportSubmission.objects.create(
        updates_requested=False, description="A report.", **kwargs
    )


def force_active(policy: TriagePolicy) -> None:
    """Simulate an existing active policy, including deliberately invalid data."""
    TriagePolicy._base_manager.filter(pk=policy.pk).update(
        status="ACTIVE",
        activated_at=timezone.now(),
        taxonomy_snapshot=snapshot_taxonomy(),
    )
    policy.refresh_from_db()


def test_missing_policy_escalates_and_flags_immediate_report() -> None:
    """An urgent cue is retained even without an approved policy."""
    submission = new_submission(reported_time_sensitivity="IMMEDIATE")
    triage_submission(submission.pk)
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.urgent_review is True
    assert submission.triage_attempts.get().reason == (
        "No approved triage policy is available."
    )


def test_policy_results_are_reviewable_proposals_and_retry_is_safe() -> None:
    """Configured rules never finalize unconfirmed reporter evidence."""
    policy = TriagePolicy.objects.create(version=1, name="Test")
    rule = TriagePolicyRule.objects.create(
        policy=policy,
        name="Impact",
        impact="SIGNIFICANT",
        target="PRIORITY",
        outcome_code="HIGH",
    )
    force_active(policy)
    submission = new_submission(reported_impact="SIGNIFICANT")
    triage_submission(submission.pk)
    triage_submission(submission.pk)
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.work_item is None
    assert submission.triage_attempts.count() == 2
    attempt = submission.triage_attempts.get(decision="PROPOSED")
    assert attempt.policy_version == "1"
    assert attempt.evidence["source"] == "reporter"
    assert attempt.field_outcomes["priority"] == {
        "state": "determined",
        "value": "HIGH",
        "matched_rule_ids": [rule.pk],
    }
    assert attempt.field_outcomes["urgency"]["state"] == "ambiguous"


def test_invalid_active_policy_fails_closed_to_review() -> None:
    """Invalid configured evidence cannot produce a proposal."""
    policy = TriagePolicy.objects.create(version=1, name="Test")
    TriagePolicyRule.objects.create(
        policy=policy,
        name="Invalid",
        impact="NOT_A_SCALE_VALUE",
        target="PRIORITY",
        outcome_code="HIGH",
    )
    force_active(policy)
    submission = new_submission(reported_impact="SIGNIFICANT")
    triage_submission(submission.pk)
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.triage_attempts.get().reason == (
        "The active triage policy is invalid."
    )


@pytest.mark.parametrize(
    ("latitude", "longitude", "state", "value"),
    [
        (1, 1, "observed", "inside"),
        (3, 3, "observed", "outside"),
        (0, 0, "ambiguous", "boundary"),
        (None, None, "ambiguous", "unknown"),
    ],
)
def test_coverage_is_evidence_not_a_scope_decision(
    latitude: float | None, longitude: float | None, state: str, value: str
) -> None:
    """Even a pin outside the configured boundary remains for human review."""
    policy = TriagePolicy.objects.create(
        version=1,
        name="Test",
        service_area={
            "type": "Polygon",
            "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]],
        },
    )
    force_active(policy)
    submission = new_submission(latitude=latitude, longitude=longitude)
    triage_submission(submission.pk)
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.work_item is None
    attempt = submission.triage_attempts.get(decision="PROPOSED")
    assert attempt.field_outcomes["geographic_coverage"] == {
        "state": state,
        "value": value,
    }


def test_invalid_active_service_area_fails_closed() -> None:
    """A malformed active boundary cannot generate misleading coverage evidence."""
    policy = TriagePolicy.objects.create(
        version=1,
        name="Test",
        service_area={"type": "Point", "coordinates": [0, 0]},
    )
    force_active(policy)
    submission = new_submission(latitude=0, longitude=0)
    triage_submission(submission.pk)
    assert submission.triage_attempts.get().reason == (
        "The active triage policy is invalid."
    )


@pytest.mark.parametrize(
    ("description", "flagged"),
    [
        ("There is a GAS LEAK near the entrance.", True),
        ("The gas leakage sensor is damaged.", False),
        ("There is no gas leak now.", True),
    ],
)
def test_configured_text_cues_flag_review_without_deciding_urgency(
    description: str, flagged: bool
) -> None:
    """Literal emergency cues flag review, including uncertain or negated text."""
    policy = TriagePolicy.objects.create(
        version=1, name="Test", urgent_review_phrases=["gas leak"]
    )
    force_active(policy)
    submission = new_submission()
    submission.description = description
    submission.save(update_fields=("description",))
    triage_submission(submission.pk)
    submission.refresh_from_db()
    assert submission.urgent_review is flagged
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.work_item is None
    proposal = submission.triage_attempts.get(decision="PROPOSED")
    assert proposal.evidence["urgent_cues"] == (["gas leak"] if flagged else [])
    assert proposal.field_outcomes["urgency"]["state"] == "ambiguous"


def test_valid_emergency_cue_is_preserved_when_other_rules_are_invalid() -> None:
    """A broken mapping must not suppress a valid urgent-review cue."""
    policy = TriagePolicy.objects.create(
        version=1, name="Test", urgent_review_phrases=["gas leak"]
    )
    TriagePolicyRule.objects.create(
        policy=policy,
        name="Invalid",
        impact="INVALID",
        target="PRIORITY",
        outcome_code="HIGH",
    )
    force_active(policy)
    submission = new_submission()
    submission.description = "Gas leak."
    submission.save(update_fields=("description",))
    triage_submission(submission.pk)
    submission.refresh_from_db()
    assert submission.urgent_review is True
    assert (
        submission.triage_attempts.get().reason
        == "The active triage policy is invalid."
    )


def test_taxonomy_drift_stops_proposals_but_preserves_urgent_cues() -> None:
    """Changed routing requires a new policy rather than reusing old semantics."""
    department = Department.objects.create(name="Facilities")
    IssueType.objects.create(name="Damage", code="DAMAGE", department=department)
    policy = TriagePolicy.objects.create(
        version=1, name="Test", urgent_review_phrases=["gas leak"]
    )
    force_active(policy)
    department.name = "Changed"
    department.save(update_fields=("name",))
    submission = new_submission()
    submission.description = "Gas leak."
    submission.save(update_fields=("description",))
    triage_submission(submission.pk)
    submission.refresh_from_db()
    assert submission.urgent_review
    assert submission.triage_state == "NEEDS_REVIEW"
    assert submission.triage_attempts.count() == 1
    assert "taxonomy" in submission.triage_attempts.get().reason


def test_legacy_active_policy_without_snapshot_goes_to_review() -> None:
    """Previously activated policies cannot silently assume current routing."""
    policy = TriagePolicy.objects.create(version=1, name="Old")
    TriagePolicy._base_manager.filter(pk=policy.pk).update(
        status="ACTIVE", activated_at=timezone.now()
    )
    submission = new_submission()
    triage_submission(submission.pk)
    assert "taxonomy" in submission.triage_attempts.get().reason
