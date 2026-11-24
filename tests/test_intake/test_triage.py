"""Tests for atomic intake triage operations."""

from collections.abc import Callable
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from employees.organisation_models import Employee
from intake.models import ContactMethod, ReportSubmission, TriageAttempt
from intake.services.review import (
    correct_location,
    recover_received,
    reject_out_of_scope,
    request_review,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def submission() -> ReportSubmission:
    """Create an untriaged public submission."""
    return ReportSubmission.objects.create(
        contact_method=ContactMethod.objects.get(code="EMAIL"),
        updates_requested=False,
        description="Something needs attention.",
    )


def test_request_review_records_one_attempt_on_retries(
    submission: ReportSubmission,
) -> None:
    """Repeated queue delivery does not duplicate the transition or audit."""
    request_review(submission.pk, reason="Location is uncertain.")
    request_review(submission.pk, reason="Location is uncertain.")

    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.triage_attempts.count() == 1
    attempt = submission.triage_attempts.get()
    assert attempt.stage == TriageAttempt.Stage.RULES
    assert attempt.reason == "Location is uncertain."


def test_request_review_rolls_back_when_audit_fails(
    submission: ReportSubmission,
) -> None:
    """A missing audit cannot leave the intake state changed."""
    with patch.object(TriageAttempt.objects, "create", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            request_review(submission.pk, reason="Location is uncertain.")

    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.RECEIVED
    assert not submission.triage_attempts.exists()


def test_reviewer_corrects_location_with_audit_and_idempotent_retry(
    submission: ReportSubmission, make_employee: Callable[..., Employee]
) -> None:
    """Reviewers can add a pin without losing the previous evidence."""
    reviewer = make_employee()
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    request_review(submission.pk, reason="Location is uncertain.")
    for _ in range(2):
        correct_location(
            submission.pk,
            reviewer=reviewer,
            latitude=Decimal("51.500000"),
            longitude=Decimal("-0.120000"),
            reason="Confirmed with reporter.",
        )

    submission.refresh_from_db()
    assert submission.latitude == Decimal("51.500000")
    assert submission.longitude == Decimal("-0.120000")
    assert submission.triage_attempts.count() == 2
    attempt = submission.triage_attempts.get(stage=TriageAttempt.Stage.HUMAN)
    assert attempt.reviewer == reviewer
    assert attempt.reason == "Confirmed with reporter."
    assert attempt.evidence["previous_location"] == {
        "latitude": None,
        "longitude": None,
    }


def test_location_correction_requires_review_and_valid_coordinates(
    submission: ReportSubmission, make_employee: Callable[..., Employee]
) -> None:
    """Invalid pins and changes outside review cannot be recorded."""
    reviewer = make_employee()
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    with pytest.raises(ValidationError):
        correct_location(
            submission.pk,
            reviewer=reviewer,
            latitude=Decimal("51"),
            longitude=Decimal("0"),
            reason="Verified.",
        )
    request_review(submission.pk, reason="Location is uncertain.")
    with pytest.raises(ValidationError):
        correct_location(
            submission.pk,
            reviewer=reviewer,
            latitude=Decimal("91"),
            longitude=Decimal("0"),
            reason="Verified.",
        )
    submission.refresh_from_db()
    assert submission.latitude is None
    assert submission.triage_attempts.count() == 1


def test_location_correction_requires_reviewer_permission(
    submission: ReportSubmission, make_employee: Callable[..., Employee]
) -> None:
    """An arbitrary employee cannot change intake locations."""
    reviewer = make_employee()
    request_review(submission.pk, reason="Location is uncertain.")
    with pytest.raises(ValidationError):
        correct_location(
            submission.pk,
            reviewer=reviewer,
            latitude=Decimal("51"),
            longitude=Decimal("0"),
            reason="Verified.",
        )
    submission.refresh_from_db()
    assert submission.latitude is None
    assert submission.triage_attempts.count() == 1


def test_stalled_triage_recovery_is_audited_and_idempotent(
    submission: ReportSubmission, make_employee: Callable[..., Employee]
) -> None:
    """Recovery records who retried and does not repeat completed processing."""
    reviewer = make_employee()
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    recover_received(submission.pk, reviewer=reviewer)
    recover_received(submission.pk, reviewer=reviewer)
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.triage_attempts.filter(decision="TRIAGE_RETRIED").count() == 1
    assert (
        submission.triage_attempts.get(decision="TRIAGE_RETRIED").reviewer == reviewer
    )


def test_stalled_recovery_rolls_back_if_triage_fails(
    submission: ReportSubmission, make_employee: Callable[..., Employee]
) -> None:
    """An error leaves a received report recoverable without a false audit."""
    reviewer = make_employee()
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    with patch(
        "intake.services.triage.orchestrator.triage_submission",
        side_effect=RuntimeError,
    ):
        with pytest.raises(RuntimeError):
            recover_received(submission.pk, reviewer=reviewer)
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.RECEIVED
    assert not submission.triage_attempts.exists()


def test_reviewer_rejects_out_of_scope_with_reason(
    submission: ReportSubmission, make_employee: Callable[..., Employee]
) -> None:
    """A single authorized reviewer can reject a report, with an audit trail."""
    reviewer = make_employee()
    request_review(submission.pk, reason="Needs review.")
    with pytest.raises(ValidationError):
        reject_out_of_scope(submission.pk, reviewer=reviewer, reason="Not ours.")
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    reviewer = Employee.objects.get(pk=reviewer.pk)
    with pytest.raises(ValidationError):
        reject_out_of_scope(submission.pk, reviewer=reviewer, reason=" ")
    reject_out_of_scope(submission.pk, reviewer=reviewer, reason="Not ours.")
    reject_out_of_scope(submission.pk, reviewer=reviewer, reason="Not ours.")
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.OUT_OF_SCOPE
    attempt = submission.triage_attempts.get(decision="OUT_OF_SCOPE")
    assert attempt.reviewer == reviewer
    assert attempt.reason == "Not ours."
    assert submission.work_item is None


def test_out_of_scope_decision_rolls_back_if_audit_fails(
    submission: ReportSubmission, make_employee: Callable[..., Employee]
) -> None:
    """A decision is never persisted without its corresponding audit."""
    reviewer = make_employee()
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    request_review(submission.pk, reason="Needs review.")
    with patch.object(TriageAttempt.objects, "create", side_effect=RuntimeError):
        with pytest.raises(RuntimeError):
            reject_out_of_scope(submission.pk, reviewer=reviewer, reason="Not ours.")
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
