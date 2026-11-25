"""Tests for access to the central review queue."""

from collections.abc import Callable

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from employees.organisation_models import Employee
from employees.work_models import Priority, Urgency, WorkItem, WorkItemStatus
from intake.models import ReportSubmission

pytestmark = pytest.mark.django_db


def test_queue_requires_review_permission_and_employee(
    client: Client, make_employee: Callable[..., Employee]
) -> None:
    """Neither anonymous users nor unrelated staff can view report details."""
    url = reverse("intake:review_queue")
    assert client.get(url).status_code == 302
    employee = make_employee()
    client.force_login(employee.user)
    assert client.get(url).status_code == 403
    user = get_user_model().objects.create_user(username="not-employee")
    user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(user)
    assert client.get(url).status_code == 403


def test_reviewer_sees_recovery_and_urgent_reports(
    client: Client, make_employee: Callable[..., Employee]
) -> None:
    """Authorized reviewers can find both pending and urgent intake."""
    employee = make_employee()
    employee.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(employee.user)
    ReportSubmission.objects.create(
        description="A report",
        updates_requested=False,
        reported_time_sensitivity="IMMEDIATE",
    )
    response = client.get(reverse("intake:review_queue"))
    assert response.status_code == 200
    assert b"Urgent review" in response.content
    assert b"Received" in response.content


def test_reviewer_can_find_and_reopen_a_final_decision(
    client: Client, make_employee: Callable[..., Employee]
) -> None:
    """Corrections require an authorized employee and a recorded reason."""
    submission = ReportSubmission.objects.create(
        description="A report", updates_requested=False, triage_state="OUT_OF_SCOPE"
    )
    url = reverse("intake:reopen_report", args=[submission.pk])
    assert client.get(url).status_code == 302
    reviewer = make_employee()
    client.force_login(reviewer.user)
    assert client.post(url, {"reason": "Recheck"}).status_code == 403
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(reviewer.user)
    listing = client.get(reverse("intake:finalized_reports"))
    assert str(submission.pk).encode() in listing.content
    assert "no-store" in listing.headers["Cache-Control"]
    assert client.post(url, {"reason": ""}).status_code == 200
    assert client.post(url, {"reason": "Recheck"}).status_code == 302
    submission.refresh_from_db()
    assert submission.triage_state == "NEEDS_REVIEW"
    assert submission.triage_attempts.get(decision="REOPENED").reason == "Recheck"


def test_review_detail_is_private_and_contains_evidence(
    client: Client, make_employee: Callable[..., Employee]
) -> None:
    """The evidence is accessible only to authorized employee reviewers."""
    submission = ReportSubmission.objects.create(
        description="A private report", updates_requested=False
    )
    url = reverse("intake:review_detail", args=[submission.pk])
    assert client.get(url).status_code == 302
    employee = make_employee()
    client.force_login(employee.user)
    assert client.get(url).status_code == 403
    employee.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(employee.user)
    response = client.get(url)
    assert response.status_code == 200
    assert b"A private report" in response.content
    assert "no-store" in response.headers["Cache-Control"]
    submission.triage_state = "OUT_OF_SCOPE"
    submission.save(update_fields=("triage_state",))
    assert client.get(url).status_code == 404


def test_authorized_reviewer_can_recover_stalled_triage(
    client: Client, make_employee: Callable[..., Employee]
) -> None:
    """Recovery is a protected POST and leaves the report for human review."""
    submission = ReportSubmission.objects.create(
        description="Pending", updates_requested=False
    )
    url = reverse("intake:recover_report", args=[submission.pk])
    assert client.post(url).status_code == 302
    reviewer = make_employee()
    client.force_login(reviewer.user)
    assert client.post(url).status_code == 403
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(reviewer.user)
    assert client.get(url).status_code == 405
    assert client.post(url).status_code == 302
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert (
        submission.triage_attempts.get(decision="TRIAGE_RETRIED").reviewer == reviewer
    )


def test_reviewer_corrects_location_with_required_reason(
    client: Client, make_employee: Callable[..., Employee]
) -> None:
    """Location changes require review permission and record an explanation."""
    submission = ReportSubmission.objects.create(
        description="A report", updates_requested=False, triage_state="NEEDS_REVIEW"
    )
    url = reverse("intake:correct_location", args=[submission.pk])
    reviewer = make_employee()
    client.force_login(reviewer.user)
    assert (
        client.post(
            url, {"latitude": "1", "longitude": "2", "reason": "Checked"}
        ).status_code
        == 403
    )
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(reviewer.user)
    assert (
        client.post(url, {"latitude": "1", "longitude": "2", "reason": ""}).status_code
        == 400
    )
    assert not submission.triage_attempts.exists()
    assert (
        client.post(
            url, {"latitude": "1", "longitude": "2", "reason": "Checked"}
        ).status_code
        == 302
    )
    submission.refresh_from_db()
    assert str(submission.latitude) == "1.000000"
    assert (
        submission.triage_attempts.get(decision="LOCATION_CORRECTED").reviewer
        == reviewer
    )
    detail = client.get(reverse("intake:review_detail", args=[submission.pk]))
    assert b"Checked" in detail.content
    assert b"Corrected pin" in detail.content


def test_reviewer_can_mark_report_out_of_scope(
    client: Client, make_employee: Callable[..., Employee]
) -> None:
    """The rejection form requires authorization and a reason."""
    submission = ReportSubmission.objects.create(
        description="A report", updates_requested=False, triage_state="NEEDS_REVIEW"
    )
    reviewer = make_employee()
    url = reverse("intake:out_of_scope", args=[submission.pk])
    client.force_login(reviewer.user)
    assert client.post(url, {"reason": "Not ours."}).status_code == 403
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(reviewer.user)
    assert client.get(url).status_code == 200
    assert client.post(url, {"reason": ""}).status_code == 200
    submission.refresh_from_db()
    assert submission.triage_state == "NEEDS_REVIEW"
    assert client.post(url, {"reason": "Not ours."}).status_code == 302
    submission.refresh_from_db()
    assert submission.triage_state == "OUT_OF_SCOPE"
    assert submission.triage_attempts.get(decision="OUT_OF_SCOPE").reviewer == reviewer


def test_reviewer_checks_resolved_duplicate_before_linking(
    client: Client,
    make_employee: Callable[..., Employee],
    make_work_item: Callable[..., WorkItem],
) -> None:
    """Resolved matches are clearly flagged and require an explicit confirmation."""
    reviewer = make_employee()
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(reviewer.user)
    work = make_work_item()
    work.status = WorkItemStatus.objects.get(code="RESOLVED")
    work.save(update_fields=("status",))
    submission = ReportSubmission.objects.create(
        description="A report",
        updates_requested=False,
        triage_state="NEEDS_REVIEW",
        latitude=work.latitude,
        longitude=work.longitude,
    )
    detail = client.get(reverse("intake:review_detail", args=[submission.pk]))
    assert b"Possible recurrence" in detail.content
    url = reverse("intake:duplicate_review", args=[submission.pk])
    assert (
        b"This may be a recurrence"
        in client.get(url, {"work_item_id": work.pk}).content
    )
    data: dict[str, object] = {"work_item_id": work.pk, "reason": "Same incident"}
    assert client.post(url, data).status_code == 200
    submission.refresh_from_db()
    assert submission.triage_state == "NEEDS_REVIEW"
    data["confirmed_not_recurrence"] = "on"
    assert client.post(url, data).status_code == 302
    submission.refresh_from_db()
    assert submission.triage_state == "DUPLICATE"
    assert submission.work_item_id == work.pk


def test_reviewer_accepts_only_with_confirmed_decisions(
    client: Client,
    make_employee: Callable[..., Employee],
    make_work_item: Callable[..., WorkItem],
) -> None:
    """The review form does not create work until all checks are confirmed."""
    reviewer = make_employee()
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(reviewer.user)
    sample = make_work_item()
    submission = ReportSubmission.objects.create(
        description="A report",
        updates_requested=False,
        triage_state="NEEDS_REVIEW",
        latitude=sample.latitude,
        longitude=sample.longitude,
    )
    url = reverse("intake:accept_report", args=[submission.pk])
    assert client.get(url).status_code == 200
    data = {
        "issue_type": sample.issue_type_id,
        "priority": Priority.objects.get(code="HIGH").pk,
        "urgency": Urgency.objects.get(code="SOON").pk,
        "scope_confirmed": "on",
        "not_duplicate_confirmed": "on",
        "reason": "Confirmed from records.",
    }
    assert client.post(url, data).status_code == 200
    assert WorkItem.objects.count() == 1
    data["location_confirmed"] = "on"
    assert client.post(url, data).status_code == 302
    submission.refresh_from_db()
    assert submission.triage_state == "ACCEPTED"
    assert submission.work_item is not None
    assert submission.work_item.status.code == "TRIAGED"
    assert submission.triage_attempts.get(decision="ACCEPTED").reviewer == reviewer
