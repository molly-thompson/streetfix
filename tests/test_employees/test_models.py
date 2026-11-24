"""Tests for employee and work models."""

from decimal import Decimal

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from employees.organisation_models import Department, Employee, IssueType
from employees.work_models import (
    CancellationReason,
    Priority,
    Urgency,
    WorkItem,
    WorkItemComment,
    WorkItemStatus,
    WorkItemStatusHistory,
)

pytestmark = pytest.mark.django_db


def test_issue_type_name_is_unique_within_department() -> None:
    """An issue type name can be reused by another department."""
    first_department = Department.objects.create(name="Roads")
    second_department = Department.objects.create(name="Parks")
    IssueType.objects.create(
        department=first_department,
        name="Damage",
        code="ROAD_DAMAGE",
    )

    duplicate = IssueType(
        department=first_department,
        name="Damage",
        code="OTHER",
    )
    with pytest.raises(ValidationError):
        duplicate.full_clean()

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            duplicate.save()

    assert (
        IssueType.objects.filter(
            department=first_department,
            name="Damage",
        ).count()
        == 1
    )

    IssueType.objects.create(
        department=second_department,
        name="Damage",
        code="PARK_DAMAGE",
    )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("latitude", Decimal("-90")),
        ("latitude", Decimal("90")),
        ("longitude", Decimal("-180")),
        ("longitude", Decimal("180")),
    ),
)
def test_work_item_accepts_coordinate_bounds(
    field_name: str, value: Decimal, work_item: WorkItem
) -> None:
    """Coordinate validators accept their inclusive geographic limits."""
    setattr(work_item, field_name, value)

    work_item.full_clean()


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("latitude", Decimal("-90.000001")),
        ("latitude", Decimal("90.000001")),
        ("longitude", Decimal("-180.000001")),
        ("longitude", Decimal("180.000001")),
    ),
)
def test_work_item_rejects_coordinates_outside_bounds(
    field_name: str, value: Decimal, work_item: WorkItem
) -> None:
    """Coordinate validators reject values just outside their geographic limits."""
    setattr(work_item, field_name, value)

    with pytest.raises(ValidationError) as error:
        work_item.full_clean()

    assert field_name in error.value.message_dict


def test_fixed_option_rows_are_seeded_with_editable_labels() -> None:
    """Fixed codes are in the database, and their labels are editable."""
    priority = Priority.objects.get(code="CRITICAL")

    assert priority.label == "Critical"
    assert "highest attention" in priority.guidance
    assert Priority._meta.get_field("code").editable is False
    assert Priority._meta.get_field("label").editable is True
    assert set(Priority.objects.values_list("code", flat=True)) == {
        "LOW",
        "NORMAL",
        "HIGH",
        "CRITICAL",
    }
    assert set(Urgency.objects.values_list("code", flat=True)) == {
        "ROUTINE",
        "SOON",
        "URGENT",
        "EMERGENCY",
    }
    assert set(WorkItemStatus.objects.values_list("code", flat=True)) == {
        "SUBMITTED",
        "TRIAGED",
        "ASSIGNED",
        "IN_PROGRESS",
        "AWAITING_INFORMATION",
        "AWAITING_PARTS",
        "ON_HOLD",
        "RESOLVED",
        "CLOSED",
        "CANCELLED",
    }
    assert set(CancellationReason.objects.values_list("code", flat=True)) == {
        "DUPLICATE",
        "NO_LONGER_REQUIRED",
        "WITHDRAWN",
        "NOT_MAINTENANCE",
        "OUT_OF_SCOPE",
        "INVALID_REQUEST",
        "OTHER",
    }

    priority.label = "Immediate attention"
    priority.save(update_fields=("label",))
    priority.refresh_from_db()

    assert priority.label == "Immediate attention"


def test_other_cancellation_reason_requires_notes(work_item: WorkItem) -> None:
    """Cancellation with OTHER cannot be saved without explanatory notes."""
    work_item.status = WorkItemStatus.objects.get(code="CANCELLED")
    work_item.ended_at = work_item.created_at
    work_item.cancellation_reason = CancellationReason.objects.get(code="OTHER")

    with pytest.raises(ValidationError) as error:
        work_item.full_clean()

    assert "cancellation_notes" in error.value.message_dict


def test_status_transition_records_history_and_end_time(
    work_item: WorkItem, employee: Employee
) -> None:
    """A cancellation records its reason, actor, timestamp, and status history."""
    cancelled = WorkItemStatus.objects.get(code="CANCELLED")
    reason = CancellationReason.objects.get(code="DUPLICATE")
    before_transition = timezone.now()

    work_item.transition_to(
        cancelled,
        changed_by=employee,
        notes="Duplicate of an existing report.",
        cancellation_reason=reason,
    )
    after_transition = timezone.now()
    work_item.refresh_from_db()

    history = WorkItemStatusHistory.objects.get(work_item=work_item)
    assert work_item.status == cancelled
    assert work_item.ended_at is not None
    assert work_item.cancellation_reason == reason
    assert work_item.cancelled_by == employee
    assert history.previous_status.code == "SUBMITTED"
    assert history.new_status == cancelled
    assert history.changed_by == employee
    assert history.notes == "Duplicate of an existing report."
    assert before_transition <= history.changed_at <= after_transition
    assert before_transition <= work_item.ended_at <= after_transition

    with pytest.raises(ValidationError, match="cannot be reopened"):
        work_item.transition_to(WorkItemStatus.objects.get(code="CLOSED"))


def test_same_status_transition_does_not_create_history(work_item: WorkItem) -> None:
    """A no-op transition leaves the persisted work item and history unchanged."""
    work_item.transition_to(work_item.status)
    work_item.refresh_from_db()

    assert work_item.status.code == "SUBMITTED"
    assert work_item.ended_at is None
    assert work_item.cancellation_reason is None
    assert work_item.cancellation_notes == ""
    assert work_item.cancelled_by is None
    assert not WorkItemStatusHistory.objects.filter(work_item=work_item).exists()


@pytest.mark.parametrize(
    ("terminal_code", "attempted_code"),
    (("CLOSED", "SUBMITTED"), ("CANCELLED", "CLOSED")),
)
def test_terminal_work_item_cannot_transition_to_another_status(
    terminal_code: str,
    attempted_code: str,
    work_item: WorkItem,
) -> None:
    """Closed and cancelled work items cannot be reopened or otherwise changed."""
    terminal_status = WorkItemStatus.objects.get(code=terminal_code)

    if terminal_code == "CANCELLED":
        work_item.transition_to(
            terminal_status,
            cancellation_reason=CancellationReason.objects.get(code="DUPLICATE"),
        )
    else:
        work_item.transition_to(terminal_status)

    history_before = list(
        WorkItemStatusHistory.objects.filter(work_item=work_item).values_list(
            "previous_status_id",
            "new_status_id",
            "notes",
        )
    )

    with pytest.raises(ValidationError, match="cannot be reopened"):
        work_item.transition_to(WorkItemStatus.objects.get(code=attempted_code))

    work_item.refresh_from_db()
    assert work_item.status == terminal_status
    assert (
        list(
            WorkItemStatusHistory.objects.filter(work_item=work_item).values_list(
                "previous_status_id",
                "new_status_id",
                "notes",
            )
        )
        == history_before
    )


def test_status_transition_rolls_back_if_history_cannot_be_written(
    monkeypatch: pytest.MonkeyPatch, work_item: WorkItem
) -> None:
    """A failed history write rolls back the status update."""

    def fail_history_write(**kwargs: object) -> None:
        raise RuntimeError("history write failed")

    monkeypatch.setattr(
        WorkItemStatusHistory.objects,
        "create",
        fail_history_write,
    )

    with pytest.raises(RuntimeError, match="history write failed"):
        work_item.transition_to(WorkItemStatus.objects.get(code="CLOSED"))

    work_item.refresh_from_db()
    assert work_item.status.code == "SUBMITTED"
    assert work_item.ended_at is None
    assert not WorkItemStatusHistory.objects.filter(work_item=work_item).exists()


def test_other_cancellation_reason_is_rejected_by_transition(
    work_item: WorkItem,
) -> None:
    """The transition operation enforces cancellation notes."""
    with pytest.raises(ValidationError) as error:
        work_item.transition_to(
            WorkItemStatus.objects.get(code="CANCELLED"),
            cancellation_reason=CancellationReason.objects.get(code="OTHER"),
            cancellation_notes=" \n\t",
        )

    assert "cancellation_notes" in error.value.message_dict
    work_item.refresh_from_db()
    assert work_item.status.code == "SUBMITTED"
    assert not WorkItemStatusHistory.objects.filter(work_item=work_item).exists()


def test_closed_transition_sets_ended_at_without_cancellation_data(
    work_item: WorkItem,
) -> None:
    """Closing a work item records its end time without a cancel reason."""
    before_transition = timezone.now()

    work_item.transition_to(WorkItemStatus.objects.get(code="CLOSED"))
    after_transition = timezone.now()
    work_item.refresh_from_db()

    assert work_item.ended_at is not None
    assert before_transition <= work_item.ended_at <= after_transition
    assert work_item.cancellation_reason is None
    assert work_item.cancelled_by is None
    history = WorkItemStatusHistory.objects.get(work_item=work_item)
    assert history.previous_status.code == "SUBMITTED"
    assert history.new_status.code == "CLOSED"
    assert history.changed_by is None
    assert history.notes == ""


def test_work_item_deletion_is_protected_by_comments_and_status_history(
    employee: Employee, work_item: WorkItem
) -> None:
    """Comments and status history retain their work item."""
    WorkItemComment.objects.create(
        work_item=work_item,
        author=employee,
        content="Inspected the location.",
    )
    work_item.transition_to(WorkItemStatus.objects.get(code="TRIAGED"))

    with pytest.raises(ProtectedError):
        work_item.delete()

    assert WorkItem.objects.filter(pk=work_item.pk).exists()
    assert WorkItemComment.objects.filter(work_item=work_item).count() == 1
    assert WorkItemStatusHistory.objects.filter(work_item=work_item).count() == 1


def test_employee_offboarding_clears_contact_details_but_keeps_attribution(
    employee: Employee, work_item: WorkItem
) -> None:
    """Offboarding disables login and clears PII without deleting work attribution."""
    assert employee.user.has_usable_password()
    WorkItemComment.objects.create(
        work_item=work_item,
        author=employee,
        content="Inspected the location.",
    )

    employee.deactivate_and_anonymize()
    employee.refresh_from_db()
    employee.user.refresh_from_db()

    assert employee.name == "Roads Employee"
    assert employee.email is None
    assert employee.user.is_active is False
    assert employee.user.email == ""
    assert employee.user.first_name == ""
    assert employee.user.last_name == ""
    assert employee.user.username.startswith("offboarded-")
    assert employee.user.has_usable_password() is False
    assert WorkItemComment.objects.get(author=employee).content == (
        "Inspected the location."
    )


def test_employees_app_models_have_permissions() -> None:
    """Django creates permissions for models outside a models.py file."""
    codenames = set(
        Permission.objects.filter(content_type__app_label="employees").values_list(
            "codename", flat=True
        )
    )

    assert {"add_workitem", "change_workitem", "add_workassignment"} <= codenames
