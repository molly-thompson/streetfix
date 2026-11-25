"""Model entry point for the employees app.

Django looks for an app's ``models`` module when it creates permissions
after migrating. The models live in ``organisation_models`` and
``work_models``; importing them here lets Django find them, so the app's
add/change/delete/view permissions exist.
"""

from .organisation_models import Department, Employee, IssueType
from .work_models import (
    CancellationReason,
    PhotoTag,
    Priority,
    Urgency,
    VisitOutcome,
    VisitReportOption,
    WorkAssignment,
    WorkItem,
    WorkItemComment,
    WorkItemPhoto,
    WorkItemReport,
    WorkItemStatus,
    WorkItemStatusHistory,
    WorkStatusTransition,
)

__all__ = [
    "CancellationReason",
    "Department",
    "Employee",
    "IssueType",
    "Priority",
    "Urgency",
    "WorkAssignment",
    "WorkItem",
    "WorkItemComment",
    "WorkItemPhoto",
    "WorkItemReport",
    "WorkItemStatus",
    "WorkItemStatusHistory",
    "WorkStatusTransition",
    "PhotoTag",
    "VisitOutcome",
    "VisitReportOption",
]
