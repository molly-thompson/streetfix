"""Atomic review operations that record their triage history."""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from employees.organisation_models import Employee
from intake.models import ReportSubmission, TriageAttempt


@transaction.atomic
def request_review(
    submission_id: int, *, reason: str, policy_version: str = ""
) -> None:
    """Send a received submission to human review exactly once."""
    if not reason.strip():
        raise ValidationError("A reason is required when requesting review.")

    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW:
        return
    if submission.triage_state != ReportSubmission.TriageState.RECEIVED:
        raise ValidationError("Only received submissions can be sent to review.")

    submission.triage_state = ReportSubmission.TriageState.NEEDS_REVIEW
    submission.save(update_fields=("triage_state",))
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.RULES,
        policy_version=policy_version,
        decision=ReportSubmission.TriageState.NEEDS_REVIEW,
        reason=reason,
    )


@transaction.atomic
def correct_location(
    submission_id: int,
    *,
    reviewer: Employee,
    latitude: Decimal,
    longitude: Decimal,
    reason: str,
) -> None:
    """Record a reviewer's location correction and its reason."""
    if not reason.strip():
        raise ValidationError("A reason is required when correcting a location.")
    if reviewer.pk is None or not reviewer.user.has_perm(
        "intake.review_reportsubmission"
    ):
        raise ValidationError("An authorized reviewer is required.")

    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.triage_state != ReportSubmission.TriageState.NEEDS_REVIEW:
        raise ValidationError("Location can only be corrected during review.")
    if submission.latitude == latitude and submission.longitude == longitude:
        return

    previous = {
        "latitude": str(submission.latitude)
        if submission.latitude is not None
        else None,
        "longitude": (
            str(submission.longitude) if submission.longitude is not None else None
        ),
    }
    submission.latitude = latitude
    submission.longitude = longitude
    submission.full_clean()
    submission.save(update_fields=("latitude", "longitude"))
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.HUMAN,
        evidence={
            "previous_location": previous,
            "corrected_location": {
                "latitude": str(submission.latitude),
                "longitude": str(submission.longitude),
            },
        },
        decision="LOCATION_CORRECTED",
        reason=reason,
        reviewer=reviewer,
    )


@transaction.atomic
def recover_received(submission_id: int, *, reviewer: Employee) -> None:
    """Retry stalled triage and audit the reviewer who requested recovery."""
    if reviewer.pk is None or not reviewer.user.has_perm(
        "intake.review_reportsubmission"
    ):
        raise ValidationError("An authorized reviewer is required.")
    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW:
        return
    if submission.triage_state != ReportSubmission.TriageState.RECEIVED:
        raise ValidationError("Only received submissions can be recovered.")
    from intake.services.triage.orchestrator import triage_submission

    triage_submission(submission_id)
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.HUMAN,
        decision="TRIAGE_RETRIED",
        reason="Reviewer retried pending triage.",
        reviewer=reviewer,
    )


@transaction.atomic
def reject_out_of_scope(submission_id: int, *, reviewer: Employee, reason: str) -> None:
    """Record an authorized human decision that a report is out of scope."""
    if reviewer.pk is None or not reviewer.user.has_perm(
        "intake.review_reportsubmission"
    ):
        raise ValidationError("An authorized reviewer is required.")
    if not reason.strip():
        raise ValidationError("A reason is required for an out-of-scope decision.")
    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.triage_state == ReportSubmission.TriageState.OUT_OF_SCOPE:
        return
    if submission.triage_state != ReportSubmission.TriageState.NEEDS_REVIEW:
        raise ValidationError("Only reports in review can be marked out of scope.")
    if submission.work_item_id is not None:
        raise ValidationError("A report linked to work cannot be marked out of scope.")
    submission.triage_state = ReportSubmission.TriageState.OUT_OF_SCOPE
    submission.save(update_fields=("triage_state",))
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.HUMAN,
        decision=ReportSubmission.TriageState.OUT_OF_SCOPE,
        reason=reason,
        reviewer=reviewer,
    )


@transaction.atomic
def reopen_final_decision(
    submission_id: int, *, reviewer: Employee, reason: str
) -> None:
    """Reopen a rejection or duplicate without modifying operational work."""
    if reviewer.pk is None or not reviewer.user.has_perm(
        "intake.review_reportsubmission"
    ):
        raise ValidationError("An authorized reviewer is required.")
    if not reason.strip():
        raise ValidationError("A reason is required to reopen a report.")
    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    previous_state = submission.triage_state
    if previous_state not in (
        ReportSubmission.TriageState.OUT_OF_SCOPE,
        ReportSubmission.TriageState.DUPLICATE,
    ):
        raise ValidationError("Only rejected or duplicate reports can be reopened.")
    if (
        previous_state == ReportSubmission.TriageState.OUT_OF_SCOPE
        and submission.work_item_id is not None
    ) or (
        previous_state == ReportSubmission.TriageState.DUPLICATE
        and submission.work_item_id is None
    ):
        raise ValidationError("The report's final decision has inconsistent work.")
    previous_work_id = submission.work_item_id
    submission.work_item = None
    submission.triage_state = ReportSubmission.TriageState.NEEDS_REVIEW
    submission.save(update_fields=("work_item", "triage_state"))
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.HUMAN,
        evidence={
            "previous_state": previous_state,
            "previous_work_id": previous_work_id,
        },
        decision="REOPENED",
        reason=reason,
        reviewer=reviewer,
    )
