"""Tests for public reporting models."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError

from employees.organisation_models import Department, Employee, IssueType
from employees.work_models import Priority, Urgency, WorkItem, WorkItemStatus
from intake.models import (
    ContactMethod,
    IssueCategory,
    IssueSubcategory,
    Reporter,
    ReportSubmission,
    ReportSubmissionPhoto,
    TriageAttempt,
)

pytestmark = pytest.mark.django_db


def create_work_item() -> WorkItem:
    """Create a work item for report submission tests."""
    department = Department.objects.create(name="Roads")
    issue_type = IssueType.objects.create(
        department=department,
        name="Pothole",
        code="POTHOLE",
    )
    return WorkItem.objects.create(
        issue_type=issue_type,
        latitude=Decimal("51.500000"),
        longitude=Decimal("-0.120000"),
        priority=Priority.objects.get(code="NORMAL"),
        urgency=Urgency.objects.get(code="ROUTINE"),
        status=WorkItemStatus.objects.get(code="SUBMITTED"),
    )


def test_contact_methods_are_seeded_and_have_fixed_codes() -> None:
    """The supported contact methods are database rows with fixed codes."""
    assert set(ContactMethod.objects.values_list("code", "label")) == {
        ("EMAIL", "Email"),
        ("TELEPHONE", "Telephone"),
        ("POST", "Post"),
    }
    assert ContactMethod._meta.get_field("code").editable is False


def test_submission_can_be_received_without_work_item_or_location() -> None:
    """A public submission is durable before operational work exists."""
    submission = ReportSubmission.objects.create(
        contact_method=ContactMethod.objects.get(code="EMAIL"),
        updates_requested=False,
        description="Something needs attention.",
    )

    submission.full_clean()
    assert submission.work_item is None
    assert submission.latitude is None
    assert submission.longitude is None
    assert submission.triage_state == ReportSubmission.TriageState.RECEIVED
    assert submission.reported_impact == ReportSubmission.ReportedImpact.UNKNOWN
    assert (
        submission.reported_time_sensitivity
        == ReportSubmission.ReportedTimeSensitivity.UNKNOWN
    )
    assert (
        submission.reported_sensitive_content
        == ReportSubmission.ReportedSensitiveContent.UNKNOWN
    )


def test_submission_can_be_anonymous_without_contact_method() -> None:
    """Reports that do not request updates need no contact details."""
    submission = ReportSubmission.objects.create(
        updates_requested=False,
        description="Something needs attention.",
    )
    submission.full_clean()
    assert submission.reporter is None
    assert submission.contact_method is None


def test_submission_requires_both_coordinates() -> None:
    """Incomplete coordinates are rejected even when validation is bypassed."""
    submission = ReportSubmission(
        updates_requested=False,
        description="Something needs attention.",
        latitude=Decimal("51.500000"),
    )
    with pytest.raises(ValidationError):
        submission.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        submission.save()


def test_submission_validates_coordinate_ranges() -> None:
    """Report coordinates use the same bounds as work-item coordinates."""
    submission = ReportSubmission(
        updates_requested=False,
        description="Something needs attention.",
        latitude=Decimal("91"),
        longitude=Decimal("-181"),
    )
    with pytest.raises(ValidationError) as error:
        submission.full_clean()
    assert {"latitude", "longitude"} <= set(error.value.message_dict)


def test_triage_attempt_preserves_evidence_and_reviewer(employee: Employee) -> None:
    """Triage history retains structured outcomes and reviewer attribution."""
    submission = ReportSubmission.objects.create(
        updates_requested=False,
        description="Something needs attention.",
    )
    attempt = TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.HUMAN,
        policy_version="draft-1",
        field_outcomes={"priority": {"status": "determined", "value": "HIGH"}},
        evidence={"impact": "significant disruption"},
        decision="NEEDS_REVIEW",
        reason="Location needs confirmation.",
        reviewer=employee,
    )

    attempt.refresh_from_db()
    assert attempt.field_outcomes["priority"]["value"] == "HIGH"
    assert attempt.evidence["impact"] == "significant disruption"
    assert attempt.reviewer == employee
    assert attempt.policy_version == "draft-1"
    with pytest.raises(ValidationError):
        attempt.save()
    with pytest.raises(ValidationError):
        attempt.delete()
    with pytest.raises(ValidationError):
        TriageAttempt.objects.filter(pk=attempt.pk).update(reason="Rewritten")
    with pytest.raises(ValidationError):
        TriageAttempt.objects.filter(pk=attempt.pk).delete()
    with pytest.raises(ProtectedError):
        submission.delete()


def test_deleting_reporter_preserves_submission_and_clears_reporter_reference() -> None:
    """Removing a reporter leaves their submitted report intact."""
    reporter = Reporter.objects.create(
        name="A Reporter",
        email="reporter@example.com",
    )
    submission = ReportSubmission.objects.create(
        work_item=create_work_item(),
        reporter=reporter,
        contact_method=ContactMethod.objects.get(code="EMAIL"),
        updates_requested=True,
        description="A pothole needs attention.",
    )

    reporter.delete()
    submission.refresh_from_db()

    assert submission.reporter is None
    assert submission.description == "A pothole needs attention."


def test_deleting_submission_cascades_to_photos() -> None:
    """Deleting a report also removes its attached photos."""
    submission = ReportSubmission.objects.create(
        work_item=create_work_item(),
        contact_method=ContactMethod.objects.get(code="EMAIL"),
        updates_requested=False,
        description="A pothole needs attention.",
    )
    photo = ReportSubmissionPhoto.objects.create(
        report_submission=submission,
        image_url="https://example.com/pothole.jpg",
    )

    submission.delete()

    assert not ReportSubmissionPhoto.objects.filter(pk=photo.pk).exists()


def test_deleting_referenced_work_item_or_contact_method_is_protected() -> None:
    """Submissions retain their work item and contact-method references."""
    work_item = create_work_item()
    contact_method = ContactMethod.objects.get(code="EMAIL")
    submission = ReportSubmission.objects.create(
        work_item=work_item,
        contact_method=contact_method,
        updates_requested=False,
        description="A pothole needs attention.",
    )

    with pytest.raises(ProtectedError):
        work_item.delete()

    with pytest.raises(ProtectedError):
        contact_method.delete()

    assert WorkItem.objects.filter(pk=work_item.pk).exists()
    submission.refresh_from_db()
    assert submission.work_item_id == work_item.pk
    assert submission.contact_method_id == contact_method.pk


def test_work_item_transition_fields_are_required_for_cancellation() -> None:
    """The report lifecycle validates cancellation through the work item model."""
    item = create_work_item()
    item.status = WorkItemStatus.objects.get(code="CANCELLED")
    item.ended_at = item.created_at

    with pytest.raises(ValidationError) as error:
        item.full_clean()

    assert "cancellation_reason" in error.value.message_dict


def test_issue_category_seed_and_configuration() -> None:
    """Seed public categories and allow active taxonomy configuration."""
    category = IssueCategory.objects.get(code="pothole")

    assert category.issue_type_code == "POTHOLE"
    assert category.active
    assert category.subcategories.filter(code="large").exists()

    category.label = "Road surface"
    category.active = False
    category.save(update_fields=("label", "active"))

    category.refresh_from_db()
    assert category.label == "Road surface"
    assert not category.active


def test_chat_metadata_rejects_unsupported_priorities() -> None:
    """Administrators cannot save priority codes the chat cannot interpret."""
    category = IssueCategory.objects.get(code="pothole")
    category.default_priority_code = "UNKNOWN"
    with pytest.raises(ValidationError) as error:
        category.full_clean()
    assert "default_priority_code" in error.value.message_dict

    subcategory = IssueSubcategory.objects.get(category=category, code="large")
    subcategory.raised_priority_code = "UNKNOWN"
    with pytest.raises(ValidationError) as error:
        subcategory.full_clean()
    assert "raised_priority_code" in error.value.message_dict
