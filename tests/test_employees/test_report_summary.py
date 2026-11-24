"""Tests for the case note drafted from a visit report."""

from typing import Any

import pytest
from django.test import Client
from django.urls import reverse

from employees import report_summary
from employees.organisation_models import Employee
from employees.work_models import WorkItem, WorkItemComment, WorkItemReport

from .test_field_work import COMPLETE_ANSWERS, photo, started

pytestmark = pytest.mark.django_db


def submitted_report(
    officer_client: Client, job: WorkItem, officer: Employee, **answers: str
) -> Any:
    """Start work, fill in the report and press Submit."""
    started(job, officer)
    return officer_client.post(
        reverse("employees:visit_report", args=[job.pk]),
        {**COMPLETE_ANSWERS, **answers, "photo": photo("after.jpg"), "finish": ""},
    )


def test_plain_summary_covers_the_answers(job: WorkItem, officer: Employee) -> None:
    """The plain summary writes out the outcome, findings and work done."""
    report = started(job, officer)
    report.outcome = WorkItemReport.Outcome.FIXED
    report.findings = "Pothole 400mm wide"
    report.work_done = "Filled with hot asphalt"
    report.extra_answers = {
        "safety_report": True,
        "safety_hazards": ["Risk to members of the public"],
        "safety_immediate": True,
    }

    text = report_summary.plain_summary(report)

    assert "Outcome: Fixed." in text
    assert "Found on site: Pothole 400mm wide" in text
    assert "Work done: Filled with hot asphalt" in text
    assert "Hazards: Risk to members of the public." in text
    assert "Needs immediate action: yes." in text


def test_submit_shows_the_summary_before_submitting(
    officer_client: Client, job: WorkItem, officer: Employee
) -> None:
    """Pressing Submit leads to the summary, and the job isn't submitted yet."""
    response = submitted_report(officer_client, job, officer)

    summary_url = reverse("employees:visit_summary", args=[job.pk])
    assert response.headers["Location"] == summary_url
    page = officer_client.get(summary_url)
    assert b"Check your summary" in page.content
    assert b"Pothole 400mm wide, 80mm deep" in page.content
    job.refresh_from_db()
    assert job.status.code == "IN_PROGRESS"


def test_approving_saves_the_summary_as_a_comment(
    officer_client: Client, job: WorkItem, officer: Employee
) -> None:
    """Approving submits the report and leaves the note on the job."""
    submitted_report(officer_client, job, officer)

    officer_client.post(
        reverse("employees:visit_summary", args=[job.pk]),
        {"summary": "Pothole filled and site left safe."},
    )

    job.refresh_from_db()
    assert job.status.code == "RESOLVED"
    comment = WorkItemComment.objects.get(work_item=job)
    assert comment.author == officer
    assert comment.content == (
        f"Visit summary, approved by {officer}:\n\nPothole filled and site left safe."
    )
    report = WorkItemReport.objects.get(work_item=job)
    assert report.ai_summary == "Pothole filled and site left safe."


def test_empty_summary_is_refused(
    officer_client: Client, job: WorkItem, officer: Employee
) -> None:
    """The officer can't approve a blank note, and nothing is submitted."""
    submitted_report(officer_client, job, officer)

    response = officer_client.post(
        reverse("employees:visit_summary", args=[job.pk]), {"summary": "   "}
    )

    assert response.status_code == 200
    assert b"The summary can&#x27;t be empty." in response.content
    job.refresh_from_db()
    assert job.status.code == "IN_PROGRESS"
    assert not WorkItemComment.objects.filter(work_item=job).exists()


def test_summary_page_needs_a_draft(
    officer_client: Client, job: WorkItem, officer: Employee
) -> None:
    """Going straight to the summary page sends the officer to the report."""
    started(job, officer)

    response = officer_client.get(reverse("employees:visit_summary", args=[job.pk]))

    assert response.headers["Location"] == reverse(
        "employees:visit_report", args=[job.pk]
    )
