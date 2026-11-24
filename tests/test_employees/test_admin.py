"""Tests for admin-managed work item transitions."""

from django.contrib import admin
from django.test import RequestFactory

from employees.admin import WorkItemAdmin
from employees.organisation_models import Employee
from employees.work_models import (
    CancellationReason,
    WorkItem,
    WorkItemStatus,
)


def test_admin_status_change_uses_transition_operation(
    db: None, work_item: WorkItem, employee: Employee
) -> None:
    """Admin cancellation records its actor and cancellation details."""
    assert work_item.status.code == "SUBMITTED"

    work_item.status = WorkItemStatus.objects.get(code="CANCELLED")
    work_item.cancellation_reason = CancellationReason.objects.get(code="OTHER")
    work_item.cancellation_notes = "The request is outside the service area."

    request = RequestFactory().post("/admin/employees/workitem/")
    request.user = employee.user
    work_item_admin = WorkItemAdmin(WorkItem, admin.site)
    form = work_item_admin.get_form(request)(instance=work_item)

    work_item_admin.save_model(request, work_item, form, change=True)
    work_item.refresh_from_db()

    history = work_item.status_history.get()
    assert history.changed_by == employee
    assert history.new_status.code == "CANCELLED"
    assert work_item.ended_at is not None
    assert work_item.cancellation_notes == "The request is outside the service area."
