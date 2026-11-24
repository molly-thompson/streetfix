"""Tests for queue ordering and recovery visibility."""

import pytest

from intake.models import ReportSubmission
from intake.services.queue import pending_reviews

pytestmark = pytest.mark.django_db


def test_queue_includes_received_and_review_cases_urgent_first() -> None:
    """Stalled intake is visible and immediate evidence is not overlooked."""
    oldest = ReportSubmission.objects.create(
        description="First", updates_requested=False, triage_state="NEEDS_REVIEW"
    )
    urgent = ReportSubmission.objects.create(
        description="Immediate",
        updates_requested=False,
        triage_state="RECEIVED",
        reported_time_sensitivity="IMMEDIATE",
    )
    flagged = ReportSubmission.objects.create(
        description="Flagged",
        updates_requested=False,
        triage_state="NEEDS_REVIEW",
        urgent_review=True,
    )
    received = ReportSubmission.objects.create(
        description="Pending", updates_requested=False, triage_state="RECEIVED"
    )
    ReportSubmission.objects.create(
        description="Complete", updates_requested=False, triage_state="OUT_OF_SCOPE"
    )
    assert list(pending_reviews().values_list("pk", flat=True)) == [
        urgent.pk,
        flagged.pk,
        oldest.pk,
        received.pk,
    ]
