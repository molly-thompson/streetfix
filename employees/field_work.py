"""Field work: what an officer does on site, from arriving to reporting.

These keep the visit report, its photos and the work item's status in
step, so views and other callers do not have to.
"""

import uuid
from pathlib import Path
from typing import Any

import cloudinary.exceptions
import cloudinary.uploader
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.db.models import QuerySet
from django.utils import timezone

from .dispatch import PRIORITY_RANK_FIELD, URGENCY_RANK_FIELD, _rank, _status
from .organisation_models import Employee
from .work_models import WorkItem, WorkItemComment, WorkItemPhoto, WorkItemReport

# Work an officer can still act on. Anything else is paused, finished or
# waiting on a manager.
NO_PHOTO_REASON_MIN_LENGTH = 15

# Where each visit outcome leaves the work item.
OUTCOME_STATUS = {
    WorkItemReport.Outcome.FIXED: "RESOLVED",
    WorkItemReport.Outcome.NO_FAULT_FOUND: "RESOLVED",
    WorkItemReport.Outcome.TEMPORARY_FIX: "ON_HOLD",
    WorkItemReport.Outcome.FURTHER_WORK: "ON_HOLD",
    WorkItemReport.Outcome.NO_ACCESS: "ON_HOLD",
}


def my_work(employee: Employee) -> QuerySet[WorkItem]:
    """Return the active work an employee is on, most pressing first."""
    return (
        WorkItem.objects.filter(
            assignments__employee=employee,
            assignments__unassigned_at__isnull=True,
            status__is_officer_active=True,
        )
        .select_related("issue_type", "priority", "urgency", "status")
        .annotate(
            priority_rank=_rank(PRIORITY_RANK_FIELD),
            urgency_rank=_rank(URGENCY_RANK_FIELD),
        )
        .order_by("priority_rank", "urgency_rank", "created_at")
        .distinct()
    )


def reported_today(employee: Employee) -> QuerySet[WorkItemReport]:
    """Return the visit reports an employee has submitted today."""
    start = timezone.localtime().replace(hour=0, minute=0, second=0, microsecond=0)
    return WorkItemReport.objects.filter(
        employee=employee, submitted_at__gte=start
    ).select_related("work_item__issue_type", "work_item__status")


def is_case_officer(work_item: WorkItem, employee: Employee) -> bool:
    """Return whether the employee is the work item's current case officer."""
    return work_item.assignments.filter(
        employee=employee, is_case_officer=True, unassigned_at__isnull=True
    ).exists()


def draft_report(work_item: WorkItem, employee: Employee) -> WorkItemReport | None:
    """Return the employee's unsubmitted report for this visit, if any."""
    return work_item.reports.filter(
        employee=employee, submitted_at__isnull=True
    ).first()


def _check_case_officer(work_item: WorkItem, employee: Employee) -> None:
    if not is_case_officer(work_item, employee):
        raise ValidationError("Only the case officer can do this.")


def arrive(work_item: WorkItem, employee: Employee) -> WorkItemReport:
    """Record that the case officer has arrived on site."""
    _check_case_officer(work_item, employee)
    if not work_item.status.is_assigned:
        raise ValidationError("You can only arrive at assigned work.")
    report = draft_report(work_item, employee) or WorkItemReport(
        work_item=work_item, employee=employee
    )
    if report.arrived_at is None:
        report.arrived_at = timezone.now()
        report.save()
    return report


def _store_photo(work_item_id: int, image: UploadedFile[Any]) -> str:
    """Save a photo and return its URL.

    Photos go to Cloudinary when it is set up, so they survive deploys;
    otherwise they are saved locally, which is enough for development.
    """
    if settings.OFFICER_PHOTOS_ON_CLOUDINARY:
        try:
            result = cloudinary.uploader.upload(
                image,
                folder=f"streetfix/work-photos/{work_item_id}",
                resource_type="image",
            )
        except cloudinary.exceptions.Error as error:
            raise ValidationError(
                "The photo could not be uploaded. Try again."
            ) from error
        return str(result["secure_url"])
    suffix = Path(image.name or "").suffix.lower() or ".jpg"
    name = default_storage.save(
        f"work-photos/{work_item_id}/{uuid.uuid4().hex}{suffix}", image
    )
    return default_storage.url(name)


def add_photo(
    report: WorkItemReport, image: UploadedFile[Any], *, tag: str, employee: Employee
) -> WorkItemPhoto:
    """Store an uploaded photo and attach it to the report."""
    if report.is_submitted:
        raise ValidationError("This report has already been submitted.")
    return WorkItemPhoto.objects.create(
        work_item_report=report,
        uploaded_by=employee,
        tag=tag,
        image_url=_store_photo(report.work_item_id, image),
    )


@transaction.atomic
def start_work(
    report: WorkItemReport, employee: Employee, *, no_photo_reason: str = ""
) -> None:
    """Start work once there is a before photo, or a reason there is none."""
    work_item = report.work_item
    _check_case_officer(work_item, employee)
    if not work_item.status.is_assigned:
        raise ValidationError("This work has already started.")
    reason = no_photo_reason.strip()
    if not report.has_before_photo():
        if len(reason) < NO_PHOTO_REASON_MIN_LENGTH:
            raise ValidationError(
                "Take a before photo, or explain why you can't "
                f"(at least {NO_PHOTO_REASON_MIN_LENGTH} characters)."
            )
        report.no_before_photo_reason = reason
        report.save(update_fields=("no_before_photo_reason",))
    work_item.transition_to(
        _status("IN_PROGRESS"), changed_by=employee, notes="Work started on site"
    )


@transaction.atomic
def submit_report(report: WorkItemReport, employee: Employee) -> None:
    """Submit the visit report and move the work item on from it."""
    work_item = report.work_item
    _check_case_officer(work_item, employee)
    if work_item.status.code != "IN_PROGRESS":
        raise ValidationError("Start the work before reporting on it.")
    report.submit()
    outcome = WorkItemReport.Outcome(report.outcome)
    work_item.transition_to(
        _status(OUTCOME_STATUS[outcome]),
        changed_by=employee,
        notes=f"Visit report: {outcome.label}",
    )


def add_comment(work_item: WorkItem, employee: Employee, text: str) -> None:
    """Leave a comment on the work item for the manager."""
    if not text.strip():
        raise ValidationError("Write your comment first.")
    WorkItemComment.objects.create(
        work_item=work_item, author=employee, content=text.strip()
    )
