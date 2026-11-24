"""Tests for public report form validation."""

import pytest
from django.utils import timezone
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from employees.organisation_models import Department, IssueType
from intake.forms import ReportSubmissionForm
from intake.models import ContactMethod, ReportSubmission, TriagePolicy

pytestmark = pytest.mark.django_db


def test_anonymous_other_report_saves_without_contact(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A report can enter review without identifying the reporter."""
    form = ReportSubmissionForm(
        {"other_selected": "on", "description": "There is a problem."}
    )
    assert form.is_valid(), form.errors
    with django_capture_on_commit_callbacks(execute=True):
        submission = form.save()
    assert submission.reporter is None
    assert submission.contact_method is None
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW


def test_updates_need_the_chosen_contact_details() -> None:
    """The selected update channel must have a matching address."""
    email = ContactMethod.objects.get(code="EMAIL")
    form = ReportSubmissionForm(
        {
            "other_selected": "on",
            "description": "There is a problem.",
            "updates_requested": "on",
            "contact_method": email.pk,
            "telephone": "0123456789",
        }
    )
    assert not form.is_valid()
    assert "email" in form.errors


def test_location_requires_both_valid_coordinates() -> None:
    """A partial map pin is not accepted."""
    form = ReportSubmissionForm(
        {"other_selected": "on", "description": "A problem.", "latitude": "51"}
    )
    assert not form.is_valid()
    assert form.non_field_errors()


def test_report_preserves_the_selected_category_for_other(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Other retains the selected parent instead of inventing a leaf."""
    category = IssueType.objects.create(
        kind=IssueType.Kind.CATEGORY, name="Places", code="PLACES"
    )
    form = ReportSubmissionForm(
        {
            "reported_issue_type": category.pk,
            "other_selected": "on",
            "description": "There is a problem.",
        }
    )
    assert form.is_valid(), form.errors
    with django_capture_on_commit_callbacks(execute=True):
        submission = form.save()
    assert submission.reported_issue_type == category


def test_report_requires_an_issue_or_other() -> None:
    """A missing category is not accepted unless Other was chosen."""
    form = ReportSubmissionForm({"description": "There is a problem."})
    assert not form.is_valid()
    assert "reported_issue_type" in form.errors


def test_sensitive_evidence_is_available_only_when_enabled(
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """Issue-specific sensitive-content evidence is not a global question."""
    department = Department.objects.create(name="Facilities")
    issue = IssueType.objects.create(
        department=department, name="Damage", code="DAMAGE"
    )
    data = {
        "reported_issue_type": issue.pk,
        "description": "There is a problem.",
        "reported_sensitive_content": "YES",
    }
    form = ReportSubmissionForm(data)
    assert not form.is_valid()
    assert "reported_sensitive_content" in form.errors
    issue.sensitive_content_enabled = True
    issue.save(update_fields=("sensitive_content_enabled",))
    form = ReportSubmissionForm(data)
    assert form.is_valid(), form.errors
    with django_capture_on_commit_callbacks(execute=True):
        submission = form.save()
    assert submission.reported_sensitive_content == "YES"


def test_approved_evidence_labels_change_words_not_codes() -> None:
    """Deployments can adapt reporter wording without changing evidence codes."""
    policy = TriagePolicy.objects.create(
        version=1,
        name="Draft",
        evidence_labels={
            "reported_impact": {
                "label": "How many people are affected?",
                "guidance": "Choose the closest description.",
                "choices": {"SEVERE": "Most people", "UNKNOWN": "Not sure"},
            }
        },
    )
    TriagePolicy._base_manager.filter(pk=policy.pk).update(
        status="ACTIVE", activated_at=timezone.now()
    )
    form = ReportSubmissionForm()
    field = form.fields["reported_impact"]
    assert field.label == "How many people are affected?"
    assert field.help_text == "Choose the closest description."
    html = str(form["reported_impact"])
    assert 'value="SEVERE">Most people' in html
    assert 'value="LIMITED">Limited' in html
