"""Tests for scheduled recovery of persisted reports."""

from datetime import timedelta
from io import StringIO
from unittest.mock import DEFAULT, patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from intake.models import ReportSubmission
from intake.services.review import request_review

pytestmark = pytest.mark.django_db


def report(*, old: bool = True) -> ReportSubmission:
    """Create a report that did not have its commit callback run."""
    submission = ReportSubmission.objects.create(
        description="A report", updates_requested=False
    )
    if old:
        ReportSubmission.objects.filter(pk=submission.pk).update(
            submitted_at=timezone.now() - timedelta(hours=1)
        )
    return submission


def test_recovery_retries_only_stalled_reports_and_is_idempotent() -> None:
    """A bounded batch transitions old reports without touching new ones."""
    first, second, fresh = report(), report(), report(old=False)
    call_command("recover_stalled_triage", older_than_minutes=10, limit=1)
    first.refresh_from_db()
    second.refresh_from_db()
    fresh.refresh_from_db()
    assert first.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert second.triage_state == ReportSubmission.TriageState.RECEIVED
    assert fresh.triage_state == ReportSubmission.TriageState.RECEIVED
    call_command("recover_stalled_triage", older_than_minutes=10)
    call_command("recover_stalled_triage", older_than_minutes=10)
    second.refresh_from_db()
    assert second.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert first.triage_attempts.count() == 1
    assert second.triage_attempts.count() == 1


def test_failed_retry_routes_to_review() -> None:
    """A failed evaluation is retained and audited for staff."""
    submission = report()
    with patch(
        "intake.management.commands.recover_stalled_triage.triage_submission",
        side_effect=RuntimeError,
    ):
        call_command("recover_stalled_triage", older_than_minutes=10)
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.triage_attempts.get().reason == "Automated triage retry failed."


def test_recovery_failure_is_reported_without_stopping_the_batch() -> None:
    """A failed fallback raises an operational error but leaves other work retryable."""
    first, second = report(), report()
    with (
        patch(
            "intake.management.commands.recover_stalled_triage.triage_submission",
            side_effect=RuntimeError,
        ),
        patch(
            "intake.management.commands.recover_stalled_triage.request_review",
            side_effect=[RuntimeError, DEFAULT],
            wraps=request_review,
        ) as review,
        pytest.raises(CommandError),
    ):
        call_command("recover_stalled_triage", older_than_minutes=10, stdout=StringIO())
    assert review.call_count == 2
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.triage_state == ReportSubmission.TriageState.RECEIVED
    assert second.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW


@pytest.mark.parametrize("age,limit", [(0, 1), (-1, 1), (1, 0)])
def test_recovery_rejects_nonpositive_options(age: int, limit: int) -> None:
    """An invalid recovery schedule cannot process reports."""
    with pytest.raises(CommandError):
        call_command("recover_stalled_triage", older_than_minutes=age, limit=limit)
