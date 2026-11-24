"""Human acceptance of a report into operational work."""

from django.core.exceptions import ValidationError
from django.db import transaction

from employees.organisation_models import Employee, IssueType
from employees.work_models import Priority, Urgency, WorkItem, WorkItemStatus
from intake.models import ReportSubmission, TriageAttempt


@transaction.atomic
def accept_report(
    submission_id: int,
    *,
    reviewer: Employee,
    issue_type_id: int,
    priority_code: str,
    urgency_code: str,
    scope_confirmed: bool,
    not_duplicate_confirmed: bool,
    location_confirmed: bool,
    reason: str,
) -> WorkItem:
    """Create one triaged work item after explicit human confirmations."""
    if reviewer.pk is None or not reviewer.user.has_perm(
        "intake.review_reportsubmission"
    ):
        raise ValidationError("An authorized reviewer is required.")
    if not reason.strip():
        raise ValidationError("A reason is required to accept a report.")
    if not all(
        value is True
        for value in (scope_confirmed, not_duplicate_confirmed, location_confirmed)
    ):
        raise ValidationError(
            "Confirm scope, duplicates, and location before acceptance."
        )
    if priority_code not in ("LOW", "NORMAL", "HIGH", "CRITICAL"):
        raise ValidationError("Choose a valid priority.")
    if urgency_code not in ("ROUTINE", "SOON", "URGENT", "EMERGENCY"):
        raise ValidationError("Choose a valid urgency.")

    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.triage_state == ReportSubmission.TriageState.ACCEPTED:
        work = submission.work_item
        if (
            work is not None
            and work.issue_type_id == issue_type_id
            and work.priority.code == priority_code
            and work.urgency.code == urgency_code
        ):
            return work
        raise ValidationError(
            "This report was already accepted with different decisions."
        )
    if submission.triage_state != ReportSubmission.TriageState.NEEDS_REVIEW:
        raise ValidationError("Only reports in review can be accepted.")
    if submission.work_item_id is not None:
        raise ValidationError("This report is already linked to work.")
    if submission.latitude is None or submission.longitude is None:
        raise ValidationError("A confirmed location is required.")

    issue_type = IssueType.objects.filter(pk=issue_type_id).first()
    if (
        issue_type is None
        or issue_type.kind != IssueType.Kind.ISSUE
        or issue_type.department_id is None
    ):
        raise ValidationError("Choose a routable issue type with a department.")
    priority = Priority.objects.filter(code=priority_code).first()
    urgency = Urgency.objects.filter(code=urgency_code).first()
    status = WorkItemStatus.objects.filter(code="TRIAGED").first()
    if priority is None or urgency is None or status is None:
        raise ValidationError("The required work options are not configured.")
    work = WorkItem(
        issue_type=issue_type,
        latitude=submission.latitude,
        longitude=submission.longitude,
        priority=priority,
        urgency=urgency,
        status=status,
    )
    work.full_clean()
    work.save()
    submission.work_item = work
    submission.triage_state = ReportSubmission.TriageState.ACCEPTED
    submission.save(update_fields=("work_item", "triage_state"))
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.HUMAN,
        field_outcomes={
            "issue_type_id": issue_type.pk,
            "department_id": issue_type.department_id,
            "priority": priority_code,
            "urgency": urgency_code,
        },
        evidence={
            "scope_confirmed": True,
            "not_duplicate_confirmed": True,
            "location_confirmed": True,
            "latitude": str(submission.latitude),
            "longitude": str(submission.longitude),
        },
        decision=ReportSubmission.TriageState.ACCEPTED,
        reason=reason,
        reviewer=reviewer,
    )
    return work
