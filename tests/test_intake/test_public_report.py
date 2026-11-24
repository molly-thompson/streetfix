"""Tests for the gated public report form."""

import pytest
from django.test import Client, override_settings
from django.urls import reverse
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from employees.organisation_models import Department, IssueType
from intake.models import ReportSubmission

pytestmark = pytest.mark.django_db


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=False)
def test_public_report_is_not_accessible_when_disabled(client: Client) -> None:
    """Neither viewing nor submitting bypasses the deployment gate."""
    url = reverse("intake:submit_report")
    assert url == "/"
    assert client.get(reverse("intake:legacy_submit_report")).status_code == 404
    assert client.post(url, {"description": "Problem"}).status_code == 404
    assert not ReportSubmission.objects.exists()
    assert b"Online reporting is not available yet." in client.get("/").content


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
    assert b"Send report" in client.get("/").content


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_root_displays_form_and_old_report_url_remains_available(
    client: Client,
) -> None:
    """The report form is on the home page and the old URL still works."""
    assert reverse("intake:submit_report") == "/"
    assert b"Send report" in client.get("/").content
    assert b"Send report" in client.get("/report/").content


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
    assert "vendor/leaflet/leaflet.js" in content


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True, INTAKE_MAP={})
def test_report_still_accepts_location_without_a_map(client: Client) -> None:
    """Missing map configuration leaves manual coordinates available."""
    response = client.get(reverse("intake:submit_report"))
    content = response.content.decode()
    assert 'id="report-map"' not in content
    assert 'id="id_latitude"' in content
    assert 'id="id_longitude"' in content
