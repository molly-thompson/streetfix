"""Dispatch operations: putting employees on work items and taking them off.

These keep work assignments and work item status in step, so views and
other callers do not have to.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Exists, F, OuterRef, QuerySet

from .organisation_models import Department, Employee
from .work_models import WorkAssignment, WorkItem, WorkItemStatus

PRIORITY_RANK_FIELD = "priority__rank"
URGENCY_RANK_FIELD = "urgency__rank"


def _rank(field: str) -> F:
    """Order lookup rows by their database rank."""
    return F(field)


def dispatchable_work(department: Department) -> QuerySet[WorkItem]:
    """Return a department's triaged, unfinished work, most pressing first.

    Each item is annotated with ``has_case_officer``.
    """
    open_case_officer = WorkAssignment.objects.filter(
        work_item=OuterRef("pk"),
        is_case_officer=True,
        unassigned_at__isnull=True,
    )
    return (
        WorkItem.objects.filter(issue_type__department=department)
        .exclude(status__is_ended=True)
        .exclude(status__is_not_yet_triaged=True)
        .select_related("issue_type", "priority", "urgency", "status")
        .annotate(
            has_case_officer=Exists(open_case_officer),
            priority_rank=_rank(PRIORITY_RANK_FIELD),
            urgency_rank=_rank(URGENCY_RANK_FIELD),
        )
        .order_by("priority_rank", "urgency_rank", "created_at")
    )


def _status(code: str) -> WorkItemStatus:
    return WorkItemStatus.objects.get(code=code)


def _check_can_dispatch(work_item: WorkItem) -> None:
    if work_item.status.is_not_yet_triaged:
        raise ValidationError("Triage this work item before assigning it.")
    if work_item.status.is_ended:
        raise ValidationError(f"{work_item.status.label} work cannot be assigned.")


@transaction.atomic
def assign_work(
    work_item: WorkItem,
    employee: Employee,
    *,
    case_officer: bool,
    dispatcher: Employee | None,
    reason: str = "",
) -> WorkAssignment:
    """Put an employee on a work item and mark triaged work as assigned."""
    _check_can_dispatch(work_item)
    if employee.department_id != work_item.issue_type.department_id:
        raise ValidationError("Only employees from the responsible department.")

    assignment = WorkAssignment.assign(
        work_item,
        employee,
        case_officer=case_officer,
        assigned_by=dispatcher,
        reason=reason,
    )
    if case_officer and work_item.status.is_triaged:
        work_item.transition_to(
            _status("ASSIGNED"),
            changed_by=dispatcher,
            notes=f"Case officer: {employee}",
        )
    return assignment


@transaction.atomic
def remove_from_work(
    assignment: WorkAssignment,
    *,
    dispatcher: Employee | None,
    reason: str = "",
) -> None:
    """Take an employee off a work item.

    Removing the case officer from assigned work returns it to triaged, so
    it shows up as needing someone again.
    """
    assignment.release(reason=reason)
    work_item = assignment.work_item
    work_item.refresh_from_db()
    still_has_case_officer = work_item.assignments.filter(
        is_case_officer=True,
        unassigned_at__isnull=True,
    ).exists()
    if (
        assignment.is_case_officer
        and not still_has_case_officer
        and work_item.status.is_assigned
    ):
        work_item.transition_to(
            _status("TRIAGED"),
            changed_by=dispatcher,
            notes=reason or "Case officer removed",
        )
