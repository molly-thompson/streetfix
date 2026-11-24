"""Tests for employees application views."""

from collections.abc import Callable
from datetime import timedelta

import pytest
from django.contrib.auth.models import Permission, User
from django.core.cache import cache
from django.test import Client
from django.urls import resolve, reverse
from django.utils import timezone

from employees import geo
from employees.dispatch import assign_work
from employees.organisation_models import Employee
from employees.views import EmployeeDashboardView
from employees.work_models import Priority, WorkItem, WorkItemStatus
from intake.models import ReportSubmission

pytestmark = pytest.mark.django_db

MakeEmployee = Callable[..., Employee]
MakeWorkItem = Callable[..., WorkItem]


def set_status(item: WorkItem, code: str) -> WorkItem:
    """Move a work item to a status directly, for test setup."""
    item.status = WorkItemStatus.objects.get(code=code)
    item.save(update_fields=("status",))
    return item


def flow_counts(client: Client) -> dict[str, int]:
    """Return the dashboard's job flow as label to count."""
    response = client.get(reverse("employees:dashboard"))
    return {stage.label: stage.count for stage in response.context["flow"]}


def test_employee_dashboard_view_url_exists_at_desired_location(
    manager_client: Client,
) -> None:
    """Test that the employee dashboard view is accessible at /employees/."""
    response = manager_client.get("/employees/")

    assert response.status_code == 200


def test_employee_dashboard_view_url_accessible_by_name(
    manager_client: Client,
) -> None:
    """Test that the employee dashboard view is accessible by its URL name."""
    response = manager_client.get(reverse("employees:dashboard"))

    assert response.status_code == 200


def test_employee_dashboard_view_uses_correct_template(
    manager_client: Client,
) -> None:
    """Test that the employee dashboard view uses the correct template."""
    response = manager_client.get(reverse("employees:dashboard"))

    assert any(
        template.name == "employees/dashboard.html" for template in response.templates
    )


def test_employee_dashboard_view_extends_manager_layout(
    manager_client: Client,
) -> None:
    """Test that the dashboard uses the shared manager layout."""
    response = manager_client.get(reverse("employees:dashboard"))

    assert any(
        template.name == "employees/manager_base.html"
        for template in response.templates
    )


def test_employee_dashboard_view_resolves_to_correct_view_class() -> None:
    """Test that the URL resolves to the EmployeeDashboardView class."""
    resolver_match = resolve("/employees/")

    assert getattr(resolver_match.func, "view_class", None) is EmployeeDashboardView


def test_employee_dashboard_view_context_contains_expected_content(
    manager_client: Client,
) -> None:
    """Test that the response contains expected content."""
    response = manager_client.get(reverse("employees:dashboard"))
    content = response.content.decode()

    assert "Operations overview" in content
    assert "job flow" in content
    assert "Needs attention" in content


def test_dashboard_requires_sign_in(client: Client) -> None:
    """Anonymous visitors are sent to sign in."""
    response = client.get(reverse("employees:dashboard"))

    assert response.status_code == 302


def test_dashboard_is_for_managers_only(
    client: Client, make_employee: MakeEmployee
) -> None:
    """Officers are sent to their jobs; other accounts are refused."""
    client.force_login(make_employee("priya").user)

    response = client.get(reverse("employees:dashboard"))

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("employees:my_jobs")

    client.force_login(
        User.objects.create_user(username="public", email="public@example.com")
    )
    assert client.get(reverse("employees:dashboard")).status_code == 403


def test_job_flow_counts_each_stage_for_the_department(
    manager_client: Client,
    manager: Employee,
    make_work_item: MakeWorkItem,
    make_employee: MakeEmployee,
) -> None:
    """Each stage counts the manager's department's jobs only."""
    make_work_item()
    set_status(make_work_item(), "TRIAGED")
    assigned = set_status(make_work_item(), "TRIAGED")
    assign_work(assigned, make_employee("priya"), case_officer=True, dispatcher=manager)
    set_status(make_work_item(), "AWAITING_PARTS")
    set_status(make_work_item(issue_code="TREE", department="Parks"), "TRIAGED")

    counts = flow_counts(manager_client)

    assert counts["Submitted"] == 1
    assert counts["Needs a case officer"] == 1
    assert counts["Assigned"] == 1
    assert counts["Paused"] == 1


def test_job_flow_uses_status_labels_from_the_admin(
    manager_client: Client, make_work_item: MakeWorkItem
) -> None:
    """Renaming a status in the admin renames its stage on the dashboard."""
    WorkItemStatus.objects.filter(code="SUBMITTED").update(label="New reports")
    make_work_item()

    counts = flow_counts(manager_client)

    assert counts["New reports"] == 1
    assert "Submitted" not in counts


def test_dashboard_headings_use_option_labels_from_the_admin(
    manager_client: Client, make_work_item: MakeWorkItem
) -> None:
    """Renamed priorities and statuses rename the dashboard's warnings."""
    Priority.objects.filter(code="CRITICAL").update(label="Top")
    WorkItemStatus.objects.filter(code="RESOLVED").update(label="Done")
    critical = set_status(make_work_item(), "TRIAGED")
    critical.priority = Priority.objects.get(code="CRITICAL")
    critical.save()

    response = manager_client.get(reverse("employees:dashboard"))
    attention = [stage.label for stage in response.context["attention"]]

    assert "Top or emergency with no case officer" in attention
    assert "Done, waiting to be closed" in attention
    assert b"<b>Top or emergency with no case officer</b>" in response.content


def test_needs_attention_flags_urgent_and_old_unassigned_work(
    manager_client: Client, make_work_item: MakeWorkItem
) -> None:
    """Critical work and work waiting over a week without anyone are flagged."""
    critical = set_status(make_work_item(), "TRIAGED")
    critical.priority = Priority.objects.get(code="CRITICAL")
    critical.save(update_fields=("priority",))
    old = set_status(make_work_item(), "TRIAGED")
    WorkItem.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=8)
    )

    response = manager_client.get(reverse("employees:dashboard"))
    attention = {stage.label: stage.count for stage in response.context["attention"]}

    assert attention["Critical or emergency with no case officer"] == 1
    assert attention["Waiting over a week for a case officer"] == 1
    assert response.context["attention_total"] == 2


def test_workforce_shows_open_jobs_and_current_work(
    manager_client: Client,
    manager: Employee,
    make_work_item: MakeWorkItem,
    make_employee: MakeEmployee,
) -> None:
    """Each employee shows their open jobs and what is in progress."""
    priya = make_employee("priya")
    current = set_status(make_work_item(), "TRIAGED")
    assign_work(current, priya, case_officer=True, dispatcher=manager)
    set_status(current, "IN_PROGRESS")
    helping = set_status(make_work_item(), "TRIAGED")
    assign_work(helping, priya, case_officer=False, dispatcher=manager)

    response = manager_client.get(reverse("employees:dashboard"))
    rows = {row.employee: row for row in response.context["workforce"]}

    assert rows[priya].open_jobs == 2
    assert rows[priya].case_officer_jobs == 1
    assert rows[priya].working_on == current
    assert response.context["working"] == 1


def test_paused_stage_links_to_its_jobs(
    manager_client: Client, make_work_item: MakeWorkItem
) -> None:
    """Selecting Paused on the overview lists just the paused jobs."""
    paused = set_status(make_work_item(), "ON_HOLD")
    set_status(make_work_item(), "TRIAGED")

    overview = manager_client.get(reverse("employees:dashboard"))
    link = reverse("employees:dispatch") + "?stage=paused"
    assert f'href="{link}"' in overview.content.decode()

    response = manager_client.get(link)
    assert [item.pk for item in response.context["stage_items"]] == [paused.pk]
    assert response.context["stage_label"] == "Paused"
    assert reverse("employees:dispatch_detail", args=[paused.pk]) in (
        response.content.decode()
    )


def test_unknown_stage_shows_all_dispatch(
    manager_client: Client, make_work_item: MakeWorkItem
) -> None:
    """An unrecognised stage falls back to the normal dispatch page."""
    set_status(make_work_item(), "TRIAGED")

    response = manager_client.get(reverse("employees:dispatch") + "?stage=nope")

    assert response.context["stage"] == ""
    assert len(response.context["unassigned"]) == 1


def test_job_page_shows_the_street_address(
    manager_client: Client,
    make_work_item: MakeWorkItem,
    settings: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The manager's job page names the street instead of raw coordinates."""
    settings.REVERSE_GEOCODING = True  # type: ignore[attr-defined]
    cache.clear()
    monkeypatch.setattr(geo, "_lookup", lambda lat, lng: "Leek Street, Digbeth, B4 7FW")
    item = set_status(make_work_item(), "TRIAGED")

    content = manager_client.get(
        reverse("employees:dispatch_detail", args=[item.pk])
    ).content.decode()

    assert "Leek Street, Digbeth, B4 7FW" in content
    assert "google.com/maps/search/?api=1&query=51.500000,-0.120000" in content


def test_sidebar_links_to_report_review_only_for_reviewers(
    manager_client: Client, manager: Employee
) -> None:
    """Managers without the review permission do not see the review queue."""
    ReportSubmission.objects.create(updates_requested=False, description="Waiting.")
    url = reverse("intake:review_queue")

    assert (
        url not in manager_client.get(reverse("employees:dashboard")).content.decode()
    )

    manager.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    content = manager_client.get(reverse("employees:dashboard")).content.decode()

    assert f'href="{url}"' in content
    assert "Report review" in content
