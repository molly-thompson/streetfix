"""Persist public submissions and preserve their reported context."""

import logging
from collections.abc import Sequence
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction

from employees.organisation_models import IssueType
from intake.models import ReportSubmission
from intake.services.photo_reservations import attach_verified_draft
from intake.services.review import request_review
from intake.services.triage.orchestrator import triage_submission

logger = logging.getLogger(__name__)


def _triage_after_save(submission: ReportSubmission) -> None:
    """Run triage after commit, retaining failed attempts for staff."""
    try:
        triage_submission(submission.pk)
    except Exception:
        logger.exception("Triage failed for submission %s", submission.pk)
        try:
            request_review(submission.pk, reason="Automated triage failed.")
        except Exception:
            logger.exception("Could not route submission %s to review", submission.pk)
    try:
        submission.refresh_from_db()
    except Exception:
        logger.exception("Could not reload submission %s", submission.pk)


@transaction.atomic
def submit_report(
    submission: ReportSubmission,
    *,
    photo_draft_id: UUID | None = None,
    photo_slot_ids: Sequence[UUID] = (),
    session_key: str = "",
) -> ReportSubmission:
    """Save a new submission and schedule triage after its transaction commits."""
    if submission.pk is not None:
        raise ValidationError("Only a new submission can be submitted.")
    if submission.work_item_id:
        raise ValidationError("A new submission cannot already have a work item.")

    if submission.updates_requested:
        method = submission.contact_method
        reporter = submission.reporter
        if method is None or reporter is None:
            raise ValidationError("Provide contact details to receive updates.")
        contact_details = {
            "EMAIL": reporter.email,
            "TELEPHONE": reporter.telephone,
            "POST": reporter.address,
        }
        if not contact_details.get(method.code, "").strip():
            raise ValidationError("Provide contact details for the chosen method.")

    selected = submission.reported_issue_type
    if selected is not None:
        if submission.other_selected and selected.kind != IssueType.Kind.CATEGORY:
            raise ValidationError("Other must be selected under a category.")
        if not submission.other_selected and selected.kind != IssueType.Kind.ISSUE:
            raise ValidationError("Choose an issue type or select Other.")
    elif not submission.other_selected:
        raise ValidationError("Choose an issue type or select Other.")

    if (
        submission.reported_sensitive_content
        != ReportSubmission.ReportedSensitiveContent.UNKNOWN
        and (selected is None or not selected.sensitive_content_enabled)
    ):
        raise ValidationError(
            "Sensitive-content evidence is not enabled for this issue type."
        )

    path: list[dict[str, int | str]] = []
    seen: set[int] = set()
    current = selected
    while current is not None:
        if current.pk in seen:
            raise ValidationError("The issue hierarchy contains a cycle.")
        seen.add(current.pk)
        path.append({"id": current.pk, "name": current.name, "code": current.code})
        current = current.parent if current.parent_id else None
    submission.reported_issue_path = list(reversed(path))
    submission.urgent_review = (
        submission.reported_time_sensitivity
        == ReportSubmission.ReportedTimeSensitivity.IMMEDIATE
    )
    submission.full_clean()
    submission.save()
    if photo_draft_id is not None:
        attach_verified_draft(
            submission_id=submission.pk,
            draft_id=photo_draft_id,
            slot_ids=photo_slot_ids,
            session_key=session_key,
        )
    elif photo_slot_ids:
        raise ValidationError("A photo upload draft is required.")
    transaction.on_commit(lambda: _triage_after_save(submission), robust=True)
    return submission
