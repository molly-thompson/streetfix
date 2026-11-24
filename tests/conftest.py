"""Shared fixtures for the test suite."""

from collections.abc import Callable
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.auth.models import User as AuthUser
from django.test import Client
from pytest_django.fixtures import Settings

from employees.organisation_models import Department, Employee, IssueType
from employees.work_models import Priority, Urgency, WorkItem, WorkItemStatus
from intake.models import Reporter
from site_settings.models import ThemeSettings

User = get_user_model()


@pytest.fixture
def theme_settings(db: None) -> ThemeSettings:
    """Provide the persisted site theme singleton."""
    return ThemeSettings.objects.create()


@pytest.fixture
def make_employee(db: None) -> Callable[..., Employee]:
    """Provide a factory for employees with linked user accounts."""

    def make(username: str = "officer", department: str = "Roads") -> Employee:
        dept, _ = Department.objects.get_or_create(name=department)
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
        )
        return Employee.objects.create(
            user=user,
            department=dept,
            email=f"{username}@example.com",
            name=username.title(),
        )

    return make


@pytest.fixture
def make_work_item(db: None) -> Callable[..., WorkItem]:
    """Provide a factory for submitted work items."""

    def make(issue_code: str = "POTHOLE", department: str = "Roads") -> WorkItem:
        dept, _ = Department.objects.get_or_create(name=department)
        issue_type, _ = IssueType.objects.get_or_create(
            department=dept,
            code=issue_code,
            defaults={"name": issue_code.replace("_", " ").title()},
        )
        return WorkItem.objects.create(
            issue_type=issue_type,
            latitude=Decimal("51.500000"),
            longitude=Decimal("-0.120000"),
            priority=Priority.objects.get(code="NORMAL"),
            urgency=Urgency.objects.get(code="ROUTINE"),
            status=WorkItemStatus.objects.get(code="SUBMITTED"),
        )

    return make


@pytest.fixture
def manager(make_employee: Callable[..., Employee]) -> Employee:
    """Provide a Roads employee allowed to manage and assign work."""
    employee = make_employee("manager")
    employee.user.user_permissions.add(
        Permission.objects.get(codename="add_workassignment")
    )
    return employee


@pytest.fixture
def manager_client(client: Client, manager: Employee) -> Client:
    """Provide a client signed in as the manager."""
    client.force_login(manager.user)
    return client


@pytest.fixture()
def test_url_path(settings: Settings) -> None:
    """Pytest fixture to configure test-specific url path."""
    settings.ROOT_URLCONF = "tests.test_site_functionality.errors.provide_errors"


@pytest.fixture
def department(db: None) -> Department:
    """Create a department for testing."""
    department, _ = Department.objects.get_or_create(name="Roads")
    return department


@pytest.fixture
def user(db: None) -> AuthUser:
    """Create a user for testing."""
    user = User.objects.create_user(
        username="employee",
        email="employee@example.com",
    )
    user.set_password("test-password")
    user.save(update_fields=("password",))
    return user


@pytest.fixture
def employee(db: None, department: Department, user: AuthUser) -> Employee:
    """Create an employee with a linked authentication user."""
    return Employee.objects.create(
        user=user,
        department=department,
        email="employee@work-email-example.com",
        name="Roads Employee",
    )


@pytest.fixture
def issue_type(db: None, department: Department) -> IssueType:
    """Create an issue type for testing."""
    issue_type, _ = IssueType.objects.get_or_create(
        department=department,
        code="POTHOLE",
        defaults={"name": "Pothole"},
    )
    return issue_type


@pytest.fixture
def work_item(db: None, issue_type: IssueType, department: Department) -> WorkItem:
    """Create a work item in its initial submitted status."""
    return WorkItem.objects.create(
        issue_type=issue_type,
        latitude=Decimal("51.500000"),
        longitude=Decimal("-0.120000"),
        priority=Priority.objects.get(code="NORMAL"),
        urgency=Urgency.objects.get(code="ROUTINE"),
        status=WorkItemStatus.objects.get(code="SUBMITTED"),
    )


@pytest.fixture
def reporter(db: None) -> Reporter:
    """Create a reporter for testing."""
    return Reporter.objects.create(
        name="A Reporter",
        email="reporter@example.com",
    )
