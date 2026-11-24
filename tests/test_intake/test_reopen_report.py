"""Tests for correcting final intake decisions."""

from collections.abc import Callable

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from employees.organisation_models import Employee
from employees.work_models import WorkItem
from intake.models import ReportSubmission
from intake.services.review import reopen_final_decision

pytestmark = pytest.mark.django_db


def reviewer_with_permission(make_employee: Callable[..., Employee]) -> Employee:
    """Create an authorized reviewer."""
    reviewer = make_employee()
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    return reviewer


@pytest.mark.parametrize("state", ["OUT_OF_SCOPE", "DUPLICATE"])
def test_reopen_preserves_history_and_never_changes_work(
    state: str,
    make_employee: Callable[..., Employee],
    make_work_item: Callable[..., WorkItem],
) -> None:
    """Prior links are audited and removed without touching the work item."""
    reviewer = reviewer_with_permission(make_employee)
    work = make_work_item() if state == "DUPLICATE" else None
    submission = ReportSubmission.objects.create(
        description="A report",
        updates_requested=False,
        triage_state=state,
        work_item=work,
    )
    reopen_final_decision(
        submission.pk, reviewer=reviewer, reason="Review the decision."
    )
    submission.refresh_from_db()
    assert submission.triage_state == "NEEDS_REVIEW"
    assert submission.work_item_id is None
    attempt = submission.triage_attempts.get(decision="REOPENED")
    assert attempt.reviewer == reviewer
    assert attempt.evidence["previous_state"] == state
    assert attempt.evidence["previous_work_id"] == (work.pk if work else None)
    if work:
        work.refresh_from_db()
        assert work.status.code == "SUBMITTED"


def test_reopen_requires_permission_reason_and_a_supported_decision(
    make_employee: Callable[..., Employee], make_work_item: Callable[..., WorkItem]
) -> None:
    """Accepted work cannot be reopened through this service."""
    reviewer = make_employee()
    work = make_work_item()
    submission = ReportSubmission.objects.create(
        description="A report",
        updates_requested=False,
        triage_state="ACCEPTED",
        work_item=work,
    )
    with pytest.raises(ValidationError, match="authorized"):
        reopen_final_decision(submission.pk, reviewer=reviewer, reason="Review")
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    reviewer.user = type(reviewer.user).objects.get(pk=reviewer.user_id)
    with pytest.raises(ValidationError, match="reason"):
        reopen_final_decision(submission.pk, reviewer=reviewer, reason=" ")
    with pytest.raises(ValidationError, match="Only rejected or duplicate"):
        reopen_final_decision(submission.pk, reviewer=reviewer, reason="Review")
    submission.refresh_from_db()
    assert submission.work_item_id == work.pk
    assert not submission.triage_attempts.exists()
