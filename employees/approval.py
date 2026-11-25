"""Manager sign-off: approving a resolved job or sending it back.

An officer's visit report leaves fixed work as resolved. A manager then
either approves it, which closes the job, or sends it back to the officer
with a note saying what needs doing.
"""

from django.core.exceptions import ValidationError
from django.db import transaction

from .dispatch import _status
from .organisation_models import Employee
from .work_models import WorkItem, WorkItemComment, WorkItemReport


def latest_report(work_item: WorkItem) -> WorkItemReport | None:
    """Return the most recently submitted visit report for the work item."""
    return (
        work_item.reports.filter(submitted_at__isnull=False)
        .select_related("employee")
        .prefetch_related("photos")
        .order_by("-submitted_at", "-pk")
        .first()
    )


def _check_awaiting_approval(work_item: WorkItem) -> WorkItemReport:
    if not work_item.status.is_awaiting_review:
        raise ValidationError("Only resolved work can be reviewed.")
    report = latest_report(work_item)
    if report is None:
        raise ValidationError("There is no visit report to review.")
    return report


@transaction.atomic
def approve(work_item: WorkItem, manager: Employee, *, note: str = "") -> None:
    """Approve the visit report and close the job."""
    _check_awaiting_approval(work_item)
    notes = "Approved by manager"
    if note.strip():
        notes = f"{notes}: {note.strip()}"
    work_item.transition_to(_status("CLOSED"), changed_by=manager, notes=notes)


@transaction.atomic
def send_back(work_item: WorkItem, manager: Employee, *, note: str) -> None:
    """Return resolved work to the officer with a note on what needs doing.

    The officer's report is reopened as a draft so they can correct it and
    submit it again, and the note is left as a comment they will see.
    """
    report = _check_awaiting_approval(work_item)
    note = note.strip()
    if not note:
        raise ValidationError("Say what needs doing before sending it back.")
    report.submitted_at = None
    report.save(update_fields=("submitted_at",))
    work_item.transition_to(
        _status("IN_PROGRESS"),
        changed_by=manager,
        notes=f"Sent back by manager: {note}",
    )
    WorkItemComment.objects.create(
        work_item=work_item,
        author=manager,
        content=f"Report sent back: {note}",
    )
