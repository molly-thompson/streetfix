"""Figures for a department manager's operations overview."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from django.db.models import Count, Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from site_settings.configuration import get_site_configuration

from .organisation_models import Department, Employee
from .work_models import Priority, Urgency, WorkAssignment, WorkItem, WorkItemStatus

# Stages of work the dispatch page can list on their own, by ?stage= value.
STAGE_FILTERS = {
    "in_progress": ("IN_PROGRESS",),
    "paused": ("AWAITING_INFORMATION", "AWAITING_PARTS", "ON_HOLD"),
    "resolved": ("RESOLVED",),
}


@dataclass(frozen=True)
class Stage:
    """A labelled count, optionally linked, with a tone for exceptions."""

    label: str
    count: int
    url_name: str | None = None
    tone: str = ""
    query: str = ""


@dataclass(frozen=True)
class WorkforceRow:
    """What one employee is doing right now."""

    employee: Employee
    open_jobs: int
    case_officer_jobs: int
    closed_today: int
    working_on: WorkItem | None

    @property
    def state(self) -> str:
        """Return working, assigned or free, for the status dot."""
        if self.working_on is not None:
            return "working"
        return "assigned" if self.open_jobs else "free"

    @property
    def progress(self) -> int:
        """Return the share of today's jobs that are closed, as a percentage."""
        total = self.closed_today + self.open_jobs
        return round(100 * self.closed_today / total) if total else 0


def _start_of_today() -> datetime:
    return timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)


def _department_work(
    department: Department, *, with_case_officer: bool | None = None
) -> QuerySet[WorkItem]:
    """Return the department's work, optionally by whether it has a case officer."""
    work = WorkItem.objects.filter(issue_type__department=department)
    if with_case_officer is None:
        return work
    has_case_officer = Exists(
        WorkAssignment.objects.filter(
            work_item=OuterRef("pk"),
            is_case_officer=True,
            unassigned_at__isnull=True,
        )
    )
    return work.filter(has_case_officer if with_case_officer else ~has_case_officer)


def _unassigned(department: Department) -> QuerySet[WorkItem]:
    """Return triaged, unfinished work with no case officer."""
    return (
        _department_work(department, with_case_officer=False)
        .exclude(status__is_ended=True)
        .exclude(status__is_not_yet_triaged=True)
    )


def needs_case_officer_count(department: Department) -> int:
    """Count triaged work waiting for a case officer."""
    return _unassigned(department).filter(status__code="TRIAGED").count()


def urgent_unassigned(department: Department, limit: int = 5) -> list[WorkItem]:
    """Return critical or emergency work with no case officer, oldest first."""
    return list(
        _unassigned(department)
        .filter(Q(priority__is_urgent=True) | Q(urgency__is_emergency=True))
        .select_related("issue_type", "priority", "urgency")
        .order_by("created_at")[:limit]
    )


def _status_labels() -> dict[str, str]:
    """Return each status's label by code, as named in the admin."""
    return dict(WorkItemStatus.objects.values_list("code", "label"))


def _label(options: QuerySet[Any], code: str) -> str:
    """Return one option's label from the admin, or its code if missing."""
    label: str | None = (
        options.filter(code=code).values_list("label", flat=True).first()
    )
    return label or code


def status_label(code: str) -> str:
    """Return a status's label as named in the admin."""
    return _label(WorkItemStatus.objects.all(), code)


def urgent_heading() -> str:
    """Name critical or emergency work with no case officer, in admin labels."""
    critical = _label(Priority.objects.all(), "CRITICAL")
    emergency = _label(Urgency.objects.all(), "EMERGENCY")
    return f"{critical} or {emergency.lower()} with no case officer"


def job_flow(department: Department) -> list[Stage]:
    """Count the department's jobs at each stage, left to right."""
    work = _department_work(department)
    labels = _status_labels()

    def stage(code: str, url_name: str | None = None) -> Stage:
        count = work.filter(status__code=code).count()
        return Stage(labels.get(code, code), count, url_name)

    return [
        stage("SUBMITTED"),
        Stage(
            "Needs a case officer",
            needs_case_officer_count(department),
            "employees:dispatch",
        ),
        stage("ASSIGNED", "employees:dispatch"),
        Stage(
            "In progress",
            work.filter(status__is_officer_active=True).count(),
            "employees:dispatch",
            query="stage=in_progress",
        ),
        Stage(
            "Paused",
            work.filter(status__is_paused=True).count(),
            "employees:dispatch",
            query="stage=paused",
        ),
        Stage(
            "Resolved",
            work.filter(status__is_awaiting_review=True).count(),
            "employees:dispatch",
            query="stage=resolved",
        ),
        Stage(
            "Closed today",
            work.filter(status__is_ended=True, ended_at__gte=_start_of_today()).count(),
        ),
    ]


def needs_attention(department: Department) -> list[Stage]:
    """Count the exceptions a manager should look at."""
    work = _department_work(department).exclude(status__is_ended=True)
    unassigned = _unassigned(department)
    labels = _status_labels()
    paused = list(
        WorkItemStatus.objects.filter(is_paused=True).values_list("label", flat=True)
    )
    resolved = labels.get("RESOLVED", "RESOLVED")
    closed = labels.get("CLOSED", "CLOSED").lower()
    return [
        Stage(
            urgent_heading(),
            unassigned.filter(
                Q(priority__is_urgent=True) | Q(urgency__is_emergency=True)
            ).count(),
            "employees:dispatch",
            "danger",
        ),
        Stage(
            "Waiting over a week for a case officer",
            unassigned.filter(
                created_at__lt=timezone.now()
                - timedelta(days=get_site_configuration().waiting_too_long_days)
            ).count(),
            "employees:dispatch",
            "warning",
        ),
        Stage(
            f"Paused ({', '.join(paused[:-1])} or {paused[-1]})",
            work.filter(status__is_paused=True).count(),
            "employees:dispatch",
            tone="warning",
            query="stage=paused",
        ),
        Stage(
            f"{resolved}, waiting to be {closed}",
            work.filter(status__is_awaiting_review=True).count(),
            "employees:dispatch",
            tone="warning",
            query="stage=resolved",
        ),
    ]


def workforce(department: Department) -> list[WorkforceRow]:
    """List the department's active employees and their current work."""
    open_rows = Q(
        work_assignments__unassigned_at__isnull=True,
    ) & ~Q(work_assignments__work_item__status__is_ended=True)
    employees = (
        Employee.objects.filter(department=department, user__is_active=True)
        .annotate(
            open_jobs=Count("work_assignments", filter=open_rows),
            case_officer_jobs=Count(
                "work_assignments",
                filter=open_rows & Q(work_assignments__is_case_officer=True),
            ),
            closed_today=Count(
                "work_assignments",
                filter=Q(
                    work_assignments__is_case_officer=True,
                    work_assignments__work_item__status__is_ended=True,
                    work_assignments__work_item__ended_at__gte=_start_of_today(),
                ),
            ),
        )
        .order_by("-open_jobs", "name")
    )
    in_progress = {
        row.employee_id: row.work_item
        for row in WorkAssignment.objects.filter(
            employee__in=employees,
            unassigned_at__isnull=True,
            work_item__status__is_officer_active=True,
        ).select_related("work_item__issue_type", "work_item__status")
    }
    return [
        WorkforceRow(
            employee=employee,
            open_jobs=employee.open_jobs,
            case_officer_jobs=employee.case_officer_jobs,
            closed_today=employee.closed_today,
            working_on=in_progress.get(employee.pk),
        )
        for employee in employees
    ]
