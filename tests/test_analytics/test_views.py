"""Tests for analytics application views."""

import pytest
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import resolve, reverse

from analytics.views import AnalyticsOverview
from employees.organisation_models import Department

pytestmark = pytest.mark.django_db


def test_analytics_overview_view_url_exists_at_desired_location(
    manager_client: Client,
) -> None:
    """Test that the analytics overview view is accessible at /analytics/."""
    response = manager_client.get("/analytics/")

    assert response.status_code == 200


def test_analytics_overview_view_url_accessible_by_name(manager_client: Client) -> None:
    """Test that the analytics overview view is accessible by its URL name."""
    response = manager_client.get(reverse("analytics:overview"))

    assert response.status_code == 200


def test_analytics_overview_view_uses_correct_template(manager_client: Client) -> None:
    """Test that the analytics overview view uses the correct template."""
    response = manager_client.get(reverse("analytics:overview"))

    assert any(
        template.name == "analytics/overview.html" for template in response.templates
    )


def test_analytics_overview_view_extends_base_template(manager_client: Client) -> None:
    """Test that the analytics overview template extends base.html."""
    response = manager_client.get(reverse("analytics:overview"))

    assert any(template.name == "base.html" for template in response.templates)


def test_analytics_overview_view_resolves_to_correct_view_class() -> None:
    """Test that the URL resolves to the AnalyticsOverview class."""
    resolver_match = resolve("/analytics/")

    assert getattr(resolver_match.func, "view_class", None) is AnalyticsOverview


def test_analytics_overview_view_context_contains_expected_content(
    manager_client: Client,
) -> None:
    """Test that the response contains expected content."""
    response = manager_client.get(reverse("analytics:overview"))
    content = response.content.decode()

    assert "Pattern discovery" in content
    assert "operational records" in content


def test_analytics_overview_requires_manager_permission(
    client: Client,
    make_employee,
) -> None:
    """Ordinary employee accounts cannot open the analytics view."""
    employee = make_employee("analyst")
    client.force_login(employee.user)

    response = client.get(reverse("analytics:overview"))

    assert response.status_code == 403


def test_analytics_overview_only_reads_employee_department(
    client: Client,
    make_employee,
    make_work_item,
) -> None:
    """A manager's findings must not include records from another department."""
    manager = make_employee("department-manager")
    manager.user.user_permissions.add(
        Permission.objects.get(codename="add_workassignment")
    )
    own_department = Department.objects.create(name="Own analytics department")
    manager.department = own_department
    manager.save(update_fields=("department",))
    make_work_item(department=own_department.name)
    other_department = Department.objects.create(name="Other analytics department")
    make_work_item(issue_code="OTHER_LIGHT", department=other_department.name)
    client.force_login(manager.user)

    response = client.get(reverse("analytics:overview"))

    assert response.status_code == 200
    assert own_department.name in response.content.decode()
