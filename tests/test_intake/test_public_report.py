"""Tests for the gated public report form."""

import re

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from employees.organisation_models import Department, IssueType
from intake.models import ContactMethod, RateLimitRecord, ReportSubmission
from intake.services.rate_limit import REPORT_SUBMISSION

pytestmark = pytest.mark.django_db


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=False)
def test_public_report_is_not_accessible_when_disabled(client: Client) -> None:
    """Neither viewing nor submitting bypasses the deployment gate."""
    url = reverse("intake:submit_report")
    assert client.get(url).status_code == 404
    assert client.post(url, {"description": "Problem"}).status_code == 404
    assert client.get(reverse("intake:report_received")).status_code == 404
    assert not ReportSubmission.objects.exists()
    assert b"Use the report form" not in client.get("/").content


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_anonymous_report_is_saved_and_redirected(
    client: Client,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A valid anonymous report enters review and redirects without exposing its ID."""
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("intake:submit_report"),
            {"other_selected": "on", "description": "An issue."},
        )
    assert response.status_code == 302
    assert response.headers["Location"] == reverse("intake:report_received")
    submission = ReportSubmission.objects.get()
    assert submission.reporter is None
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert (
        b"Send report"
        in client.get(response.headers["Location"].replace("received/", "")).content
    )


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_chat_and_form_link_to_each_other(client: Client) -> None:
    """Residents can pick either way of reporting."""
    assert reverse("intake:submit_report").encode() in client.get("/").content
    assert (
        reverse("intake:form_intake").encode()
        in client.get(reverse("intake:submit_report")).content
    )


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_submissions_are_limited_per_address(client: Client) -> None:
    """An address that exceeds the hourly limit cannot save more reports."""
    data = {"other_selected": "on", "description": "An issue."}
    for _ in range(REPORT_SUBMISSION.limit):
        assert client.post(reverse("intake:submit_report"), data).status_code == 302
    response = client.post(reverse("intake:submit_report"), data)
    assert response.status_code == 200
    assert b"Too many requests" in response.content
    assert ReportSubmission.objects.count() == REPORT_SUBMISSION.limit


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_submission_fails_closed_without_a_client_address(client: Client) -> None:
    """A deployment without a trusted address header cannot accept reports."""
    response = client.post(
        reverse("intake:submit_report"),
        {"other_selected": "on", "description": "An issue."},
        REMOTE_ADDR="",
    )
    assert response.status_code == 200
    assert b"valid client IP" in response.content
    assert not ReportSubmission.objects.exists()
    assert not RateLimitRecord.objects.exists()


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_invalid_report_preserves_input_without_saving(client: Client) -> None:
    """An invalid report displays errors and keeps the supplied description."""
    response = client.post(
        reverse("intake:submit_report"), {"description": "An issue."}
    )
    assert response.status_code == 200
    assert b"An issue." in response.content
    assert b"Choose an issue or select Other." in response.content
    assert not ReportSubmission.objects.exists()
    assert not RateLimitRecord.objects.exists()


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_switched_off_issue_types_are_not_offered(client: Client) -> None:
    """Only active issue types appear in the form and its script data."""
    IssueType.objects.filter(code="POTHOLE").update(active=False)
    content = client.get(reverse("intake:submit_report")).content.decode()
    assert "Pothole" not in content
    assert "Graffiti" in content


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_contact_methods_are_available_to_the_form_script(client: Client) -> None:
    """The progressive disclosure script learns which method needs which field."""
    email = ContactMethod.objects.get(code="EMAIL")
    content = client.get(reverse("intake:submit_report")).content.decode()
    assert f'"{email.pk}": "EMAIL"' in content


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_taxonomy_has_path_labels_and_safe_json(client: Client) -> None:
    """The form remains understandable without JavaScript and escapes issue names."""
    category = IssueType.objects.create(
        kind=IssueType.Kind.CATEGORY, name="Parks", code="PARKS"
    )
    department = Department.objects.create(name="Facilities")
    IssueType.objects.create(
        parent=category,
        department=department,
        name="Damage <script>",
        code="DAMAGE",
    )
    response = client.get(reverse("intake:submit_report"))
    assert response.status_code == 200
    content = response.content.decode()
    assert "Parks / Damage &lt;script&gt;" in content
    assert r"Damage \u003Cscript\u003E" in content


@override_settings(
    INTAKE_PUBLIC_REPORTING_ENABLED=True,
    INTAKE_MAP={
        "tile_url": "https://maps.example.test/{z}/{x}/{y}.png",
        "attribution": "Maps <script>",
        "latitude": "51",
        "longitude": "-1",
        "zoom": "13",
    },
)
def test_configured_map_is_optional_and_attribution_is_escaped(client: Client) -> None:
    """Only configured maps load, and attribution is rendered as text."""
    response = client.get(reverse("intake:submit_report"))
    content = response.content.decode()
    assert 'id="report-map"' in content
    assert "Maps &lt;script&gt;" in content
    assert re.search(r"vendor/leaflet/leaflet(\.[0-9a-f]+)?\.js", content)
    assert re.search(r"marker-icon(\.[0-9a-f]+)?\.png", content)


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True, INTAKE_MAP={})
def test_report_still_accepts_location_without_a_map(client: Client) -> None:
    """Missing map configuration leaves manual coordinates available."""
    response = client.get(reverse("intake:submit_report"))
    content = response.content.decode()
    assert 'id="report-map"' not in content
    assert 'id="id_latitude"' in content
    assert 'id="id_longitude"' in content
