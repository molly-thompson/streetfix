"""Fixtures shared by the field work and visit summary tests."""

from collections.abc import Callable

import pytest
from django.test import Client

from employees.dispatch import assign_work
from employees.organisation_models import Employee
from employees.work_models import WorkItem, WorkItemStatus


@pytest.fixture
def officer(make_employee: Callable[..., Employee]) -> Employee:
    """Provide a Roads officer."""
    return make_employee("priya")


@pytest.fixture
def job(
    make_work_item: Callable[..., WorkItem], officer: Employee, manager: Employee
) -> WorkItem:
    """Provide triaged work with the officer as case officer."""
    item = make_work_item()
    item.transition_to(WorkItemStatus.objects.get(code="TRIAGED"))
    assign_work(item, officer, case_officer=True, dispatcher=manager)
    item.refresh_from_db()
    return item


@pytest.fixture
def officer_client(client: Client, officer: Employee) -> Client:
    """Provide a client signed in as the officer."""
    client.force_login(officer.user)
    return client
