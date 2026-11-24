"""Tests for recording the reporter's issue selection."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from employees.organisation_models import Department, IssueType
from intake.models import ContactMethod, Reporter, ReportSubmission
from intake.services.photo_reservations import create_photo_draft, reserve_photo_slot
from intake.services.submission import submit_report

pytestmark = pytest.mark.django_db


def new_submission(**kwargs: object) -> ReportSubmission:
    """Build a report without creating operational work."""
    return ReportSubmission(
        contact_method=ContactMethod.objects.get(code="EMAIL"),
        updates_requested=False,
        description="Something needs attention.",
        **kwargs,
    )


def test_submission_snapshots_selected_path_and_requests_review(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Later taxonomy changes do not rewrite the reporter's selection."""
    category = IssueType.objects.create(
        kind=IssueType.Kind.CATEGORY, name="Places", code="PLACES"
    )
    department = Department.objects.create(name="Facilities")
    issue = IssueType.objects.create(
        parent=category, department=department, name="Damage", code="DAMAGE"
    )

    with django_capture_on_commit_callbacks(execute=True):
        submission = submit_report(new_submission(reported_issue_type=issue))
    category.name = "Renamed"
    category.save(update_fields=("name",))

    assert submission.work_item is None
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert [entry["name"] for entry in submission.reported_issue_path] == [
        "Places",
        "Damage",
    ]
    assert submission.triage_attempts.count() == 1


def test_other_preserves_parent_and_never_guesses_issue_type(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Other under a category stays a human-review decision."""
    category = IssueType.objects.create(
        kind=IssueType.Kind.CATEGORY, name="Places", code="PLACES"
    )
    with django_capture_on_commit_callbacks(execute=True):
        submission = submit_report(
            new_submission(reported_issue_type=category, other_selected=True)
        )
    assert submission.reported_issue_type == category
    assert submission.other_selected is True
    assert submission.reported_issue_path == [
        {"id": category.pk, "name": "Places", "code": "PLACES"}
    ]
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW


def test_submission_rejects_unresolved_category_without_other() -> None:
    """A grouping category is not a routable issue type."""
    category = IssueType.objects.create(
        kind=IssueType.Kind.CATEGORY, name="Places", code="PLACES"
    )
    with pytest.raises(ValidationError):
        submit_report(new_submission(reported_issue_type=category))
    assert not ReportSubmission.objects.exists()


def test_updates_require_details_for_the_chosen_contact_method(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """An update request must include usable contact details."""
    submission = new_submission(other_selected=True)
    submission.updates_requested = True
    with pytest.raises(ValidationError):
        submit_report(submission)
    submission.reporter = Reporter.objects.create(telephone="0123456789")
    with pytest.raises(ValidationError):
        submit_report(submission)
    submission.reporter.email = "reporter@example.test"
    submission.reporter.save()
    with django_capture_on_commit_callbacks(execute=True):
        result = submit_report(submission)
    assert result.reporter == submission.reporter


def test_submission_rejects_sensitive_evidence_when_not_enabled() -> None:
    """Callers cannot bypass issue-specific evidence eligibility."""
    department = Department.objects.create(name="Facilities")
    issue = IssueType.objects.create(
        department=department, name="Damage", code="DAMAGE"
    )
    submission = new_submission(
        reported_issue_type=issue,
        reported_sensitive_content=ReportSubmission.ReportedSensitiveContent.YES,
    )
    with pytest.raises(ValidationError):
        submit_report(submission)
    assert not ReportSubmission.objects.exists()


def test_submission_survives_triage_failure_and_goes_to_review(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A failure after submission cannot discard the report."""
    with patch(
        "intake.services.submission.triage_submission", side_effect=RuntimeError
    ):
        with django_capture_on_commit_callbacks(execute=True):
            submission = submit_report(new_submission(other_selected=True))
    assert ReportSubmission.objects.filter(pk=submission.pk).exists()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.triage_attempts.get().reason == "Automated triage failed."


def test_triage_waits_for_outer_transaction_commit(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A report is not evaluated while its surrounding transaction can roll back."""
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            submission = submit_report(new_submission(other_selected=True))
            assert submission.triage_state == ReportSubmission.TriageState.RECEIVED
            assert not submission.triage_attempts.exists()
        assert submission.triage_state == ReportSubmission.TriageState.RECEIVED
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW


def test_failed_triage_and_fallback_leave_report_pending(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Even a database failure during fallback leaves the report for recovery."""
    submission = new_submission(
        other_selected=True, reported_time_sensitivity="IMMEDIATE"
    )
    with (
        patch("intake.services.submission.triage_submission", side_effect=RuntimeError),
        patch("intake.services.submission.request_review", side_effect=RuntimeError),
    ):
        with django_capture_on_commit_callbacks(execute=True):
            submit_report(submission)
    submission.refresh_from_db()
    assert submission.triage_state == ReportSubmission.TriageState.RECEIVED
    assert submission.urgent_review is True


def test_submission_attaches_only_all_verified_session_photos(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Photos and their report commit together without silently dropping a slot."""
    draft = create_photo_draft(
        session_key="session", expires_at=timezone.now() + timedelta(hours=2)
    )
    first = reserve_photo_slot(draft_id=draft.pk, session_key="session")
    second = reserve_photo_slot(draft_id=draft.pk, session_key="session")
    first.asset_id, first.format, first.size_bytes, first.version = "asset", "png", 4, 1
    first.save()
    with pytest.raises(ValidationError, match="All selected photos"):
        submit_report(
            new_submission(other_selected=True),
            photo_draft_id=draft.pk,
            photo_slot_ids=[first.pk, second.pk],
            session_key="session",
        )
    assert not ReportSubmission.objects.exists()
    second.asset_id, second.format, second.size_bytes, second.version = (
        "asset-two",
        "jpeg",
        5,
        1,
    )
    second.save()
    with pytest.raises(ValidationError, match="unavailable"):
        submit_report(
            new_submission(other_selected=True),
            photo_draft_id=draft.pk,
            photo_slot_ids=[first.pk, second.pk],
            session_key="another-session",
        )
    assert not ReportSubmission.objects.exists()
    with pytest.raises(ValidationError, match="All selected photos"):
        submit_report(
            new_submission(other_selected=True),
            photo_draft_id=draft.pk,
            photo_slot_ids=[first.pk],
            session_key="session",
        )
    with django_capture_on_commit_callbacks(execute=True):
        submission = submit_report(
            new_submission(other_selected=True),
            photo_draft_id=draft.pk,
            photo_slot_ids=[first.pk, second.pk],
            session_key="session",
        )
    draft.refresh_from_db()
    assert draft.submission_id == submission.pk
    assert submission.triage_state == "NEEDS_REVIEW"
