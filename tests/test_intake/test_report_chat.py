"""Tests for the public report chat and its API."""

import base64
import json
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.urls import reverse
from django.utils import timezone
from pytest_django.fixtures import Settings

from employees.organisation_models import Department, IssueType
from employees.work_models import WorkItem, WorkItemStatus
from intake.chat import locate, reference_for
from intake.models import Reporter, ReportSubmission

pytestmark = pytest.mark.django_db

PNG_1PX = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQ"
    "GAhKmMIQAAAABJRU5ErkJggg=="
)


def chat_report(**overrides: Any) -> dict[str, Any]:
    """Return a report shaped like the one the chat sends."""
    case: dict[str, Any] = {
        "category": "light",
        "sub_issue": "Wires hanging or exposed",
        "category_source": "Chosen by reporter",
        "description": None,
        "chat_language": "Polish",
        "priority_suggested": "Urgent",
        "priority_reasons": ['Raised to Urgent: "Wires hanging or exposed"'],
        "reporter_urgency": "High",
        "location": {"postcode": "B29 1AA", "description": "Outside the Co-op"},
        "duplicate_of": None,
        "possible_duplicate_of": None,
        "photo": None,
    }
    reporter: dict[str, Any] = {
        "name": "Amir",
        "email": "amir@example.com",
        "phone": None,
        "preferred_contact": "Email",
        "preferred_language": "Polish",
        "wants_updates": True,
    }
    case.update(overrides.pop("case", {}))
    reporter.update(overrides.pop("reporter", {}))
    return {"case": case, "reporter": reporter}


@pytest.fixture
def post_report(client: Client) -> Callable[[dict[str, Any]], Any]:
    """Provide a helper that posts a chat report as JSON."""

    def post(payload: dict[str, Any]) -> Any:
        return client.post(
            reverse("intake:create_report"),
            data=json.dumps(payload),
            content_type="application/json",
        )

    return post


def test_report_chat_page_is_public(client: Client) -> None:
    """Residents can open the chat without signing in."""
    response = client.get(reverse("intake:form_intake"))

    assert response.status_code == 200
    assert "js/report-chat." in response.content.decode()
    assert "csrftoken" in response.cookies


def test_report_chat_uses_site_layout_and_theme(client: Client) -> None:
    """The chat extends the site template, so it gets UIkit and the theme."""
    response = client.get(reverse("intake:form_intake"))
    content = response.content.decode()

    assert any(template.name == "base.html" for template in response.templates)
    assert "uikit/uikit.min" in content
    assert "css/theme" in content
    assert content.index("css/theme") < content.index("css/report-chat")


def test_report_chat_shows_the_site_navbar(client: Client) -> None:
    """The report chat keeps the site brand and the shared navigation links."""
    content = client.get(reverse("intake:form_intake")).content.decode()

    assert "uk-logo" in content
    assert '<a href="/employees/">Employees</a>' in content
    assert '<a href="/analytics/">Analytics</a>' not in content


def test_staff_panel_hidden_from_public(client: Client) -> None:
    """The triage panel is not shown to residents."""
    response = client.get(reverse("intake:form_intake"))

    assert 'id="casePanel"' not in response.content.decode()


def test_staff_panel_shown_to_staff(client: Client) -> None:
    """Signed-in staff see the triage panel."""
    user = get_user_model().objects.create_user(
        username="triage", email="triage@example.com", is_staff=True
    )
    client.force_login(user)

    response = client.get(reverse("intake:form_intake"))

    assert 'id="casePanel"' in response.content.decode()


def test_old_report_link_redirects_to_home(client: Client) -> None:
    """Links to /report/ from before the chat became the home page still work."""
    response = client.get("/report/")

    assert response.status_code == 302
    assert response.headers["Location"] == reverse("intake:form_intake")


def test_report_creates_submitted_work_item(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """A chat report creates a work item that still needs triage."""
    response = post_report(chat_report())

    assert response.status_code == 201
    work_item = WorkItem.objects.get()
    assert response.json()["reference"] == reference_for(work_item)
    assert work_item.status.code == "SUBMITTED"
    assert work_item.priority.code == "CRITICAL"
    assert work_item.urgency.code == "URGENT"
    assert work_item.issue_type.code == "STREETLIGHT"
    assert work_item.issue_type.department is not None
    assert work_item.issue_type.department.name == "Street Lighting"
    assert (
        ReportSubmission.objects.get().triage_state
        == ReportSubmission.TriageState.LEGACY_LINKED
    )


def test_submission_keeps_triage_reasons_for_officer(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """The submission explains the suggestion and the reporter's language."""
    post_report(chat_report())

    text = ReportSubmission.objects.get().description
    assert "Wires hanging or exposed" in text
    assert "B29 1AA, Outside the Co-op" in text
    assert "needs confirming" in text
    assert "Reported through the Polish chat." in text


def test_existing_issue_type_is_reused(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Issue types set up in Admin keep their own department."""
    roads = Department.objects.create(name="Roads")
    pothole = IssueType.objects.get(code="POTHOLE")
    pothole.department = roads
    pothole.save()
    issue_types = IssueType.objects.count()

    post_report(chat_report(case={"category": "pothole"}))

    assert WorkItem.objects.get().issue_type == pothole
    assert IssueType.objects.count() == issue_types


def test_inactive_issue_type_goes_to_triage_desk(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """A category the team has switched off is no longer offered to reporters."""
    IssueType.objects.filter(code="POTHOLE").update(active=False)

    post_report(chat_report(case={"category": "pothole"}))

    assert WorkItem.objects.get().issue_type.code == "OTHER"


def test_report_is_refused_when_no_issue_type_is_available(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """The chat never invents issue types to keep a report."""
    IssueType.objects.filter(code__in=("POTHOLE", "OTHER")).update(active=False)

    response = post_report(chat_report(case={"category": "pothole"}))

    assert response.status_code == 400
    assert not WorkItem.objects.exists()
    assert not ReportSubmission.objects.exists()


def test_unknown_category_goes_to_triage_desk(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Reports the chat could not categorise go to a person, not a low bucket."""
    post_report(chat_report(case={"category": "not-a-category"}))

    assert (
        WorkItem.objects.filter(issue_type__department__name="Triage desk").count() == 1
    )


def test_reporter_saved_when_updates_wanted(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Contact details are stored only for reporters who want updates."""
    post_report(chat_report())

    submission = ReportSubmission.objects.get()
    assert submission.updates_requested is True
    assert submission.reporter is not None
    assert submission.reporter.email == "amir@example.com"
    assert submission.contact_method is not None
    assert submission.contact_method.code == "EMAIL"


def test_no_personal_details_without_updates(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """A reporter who wants no updates leaves no personal details."""
    post_report(
        chat_report(reporter={"wants_updates": False, "email": "x@example.com"})
    )

    submission = ReportSubmission.objects.get()
    assert submission.updates_requested is False
    assert submission.reporter is None
    assert not Reporter.objects.exists()


def test_text_message_contact_maps_to_telephone(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Text and phone updates both use the telephone contact method."""
    post_report(
        chat_report(
            reporter={
                "preferred_contact": "Text message",
                "email": None,
                "phone": "07700 900123",
            }
        )
    )

    method = ReportSubmission.objects.get().contact_method
    assert method is not None
    assert method.code == "TELEPHONE"


def test_unknown_postcode_location_is_flagged(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Without coordinates the officer is told the map pin is approximate."""
    post_report(
        chat_report(
            case={"location": {"postcode": None, "description": "By the roundabout"}}
        )
    )

    assert "Map pin is approximate" in ReportSubmission.objects.get().description


def test_confirmed_duplicate_joins_existing_work_item(
    post_report: Callable[[dict[str, Any]], Any],
    make_work_item: Callable[..., WorkItem],
) -> None:
    """A report the resident confirmed as a duplicate joins the open job."""
    existing = make_work_item()

    post_report(chat_report(case={"duplicate_of": reference_for(existing)}))

    assert WorkItem.objects.count() == 1
    assert existing.submissions.count() == 1


def test_duplicate_of_closed_work_starts_new_job(
    post_report: Callable[[dict[str, Any]], Any],
    make_work_item: Callable[..., WorkItem],
) -> None:
    """A closed job is not reopened by a new report."""
    existing = make_work_item()
    existing.status = WorkItemStatus.objects.get(code="CLOSED")
    existing.save()

    post_report(chat_report(case={"duplicate_of": reference_for(existing)}))

    assert WorkItem.objects.count() == 2


def test_photo_is_stored(
    post_report: Callable[[dict[str, Any]], Any],
    settings: Settings,
    tmp_path: Path,
) -> None:
    """A photo from the chat is saved and linked to the submission."""
    settings.MEDIA_ROOT = tmp_path
    post_report(chat_report(case={"photo": f"data:image/png;base64,{PNG_1PX}"}))

    photo = ReportSubmission.objects.get().photos.get()
    assert photo.image_url.endswith(".png")
    assert len(list(tmp_path.rglob("*.png"))) == 1


def test_report_kept_when_photo_cannot_be_stored(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """A storage failure keeps the report and tells the officer."""
    with mock.patch(
        "intake.chat.default_storage.save", side_effect=OSError("read-only")
    ):
        response = post_report(
            chat_report(case={"photo": f"data:image/png;base64,{PNG_1PX}"})
        )

    submission = ReportSubmission.objects.get()
    assert response.status_code == 201
    assert not submission.photos.exists()
    assert "could not be saved" in submission.description


def test_oversized_photo_is_rejected(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Photos over the limit are refused and nothing is saved."""
    big = base64.b64encode(b"0" * (5 * 1024 * 1024 + 1)).decode()

    response = post_report(chat_report(case={"photo": f"data:image/jpeg;base64,{big}"}))

    assert response.status_code == 400
    assert not WorkItem.objects.exists()


@pytest.mark.parametrize(
    "body",
    [b"not json", b"{}", json.dumps({"case": "x"}).encode()],
)
def test_unreadable_report_is_rejected(client: Client, body: bytes) -> None:
    """Malformed bodies get a 400 instead of a server error."""
    response = client.post(
        reverse("intake:create_report"), data=body, content_type="application/json"
    )

    assert response.status_code == 400


def test_report_without_any_location_is_rejected(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """An officer needs at least a postcode or a description."""
    response = post_report(
        chat_report(case={"location": {"postcode": None, "description": None}})
    )

    assert response.status_code == 400


def test_create_report_requires_csrf_token() -> None:
    """The API keeps Django's CSRF protection."""
    client = Client(enforce_csrf_checks=True)

    blocked = client.post(
        reverse("intake:create_report"),
        data=json.dumps(chat_report()),
        content_type="application/json",
    )
    client.get(reverse("intake:form_intake"))
    allowed = client.post(
        reverse("intake:create_report"),
        data=json.dumps(chat_report()),
        content_type="application/json",
        headers={"X-CSRFToken": client.cookies["csrftoken"].value},
    )

    assert blocked.status_code == 403
    assert allowed.status_code == 201


def test_report_status_by_reference(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Anyone with a reference can see its status, but no personal details."""
    work_item = make_work_item()

    response = client.get(
        reverse("intake:report_status", args=[reference_for(work_item)])
    )

    assert response.status_code == 200
    assert response.json() == {
        "reference": reference_for(work_item),
        "status": "Submitted",
        "issue": "Pothole",
    }


def test_report_status_unknown_reference(client: Client) -> None:
    """Unknown references return 404."""
    response = client.get(reverse("intake:report_status", args=["SF-99999"]))

    assert response.status_code == 404


def test_locate_uses_postcodes_io(settings: Settings) -> None:
    """Postcodes are turned into map coordinates."""
    settings.POSTCODE_LOOKUP = True
    cache.clear()
    body = json.dumps({"result": {"latitude": 52.43, "longitude": -1.93}}).encode()
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = body
    with mock.patch(
        "intake.chat.urllib.request.urlopen", return_value=response
    ) as call:
        assert locate("b29 1aa") is not None
    assert call.call_args.args[0].endswith("/B291AA")


def test_locate_skips_invalid_postcodes(settings: Settings) -> None:
    """Invalid postcodes are never sent to the lookup service."""
    settings.POSTCODE_LOOKUP = True
    with mock.patch("intake.chat.urllib.request.urlopen") as call:
        assert locate("not a postcode") is None
    call.assert_not_called()


NEAR_POTHOLE = (Decimal("51.500900"), Decimal("-0.120000"))  # ~100 m north
FAR_AWAY = (Decimal("51.520000"), Decimal("-0.120000"))  # ~2 km north


def nearby(client: Client, category: str = "pothole") -> Any:
    """Ask the nearby endpoint about a postcode."""
    return client.get(
        reverse("intake:nearby_report"),
        {"category": category, "postcode": "SW1A 1AA"},
    ).json()


def test_nearby_finds_open_job_of_same_type(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """An open pothole about 100 m away is offered as a possible duplicate."""
    existing = make_work_item()  # pothole at 51.5, -0.12

    with mock.patch("intake.chat.locate", return_value=NEAR_POTHOLE):
        result = nearby(client)

    assert result["match"]["reference"] == reference_for(existing)
    assert result["match"]["days_ago"] == 0


def test_nearby_ignores_far_away_jobs(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Jobs further than the radius are not offered."""
    make_work_item()

    with mock.patch("intake.chat.locate", return_value=FAR_AWAY):
        assert nearby(client) == {"match": None}


def test_nearby_ignores_other_issue_types(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """A nearby graffiti job is not a duplicate of a pothole."""
    make_work_item(issue_code="GRAFFITI")

    with mock.patch("intake.chat.locate", return_value=NEAR_POTHOLE):
        assert nearby(client) == {"match": None}


@pytest.mark.parametrize("status", ["RESOLVED", "CLOSED", "CANCELLED"])
def test_nearby_ignores_finished_jobs(
    client: Client, make_work_item: Callable[..., WorkItem], status: str
) -> None:
    """Finished jobs are not offered, so a new problem gets its own job."""
    existing = make_work_item()
    WorkItem.objects.filter(pk=existing.pk).update(
        status=WorkItemStatus.objects.get(code=status)
    )

    with mock.patch("intake.chat.locate", return_value=NEAR_POTHOLE):
        assert nearby(client) == {"match": None}


def test_nearby_ignores_old_jobs(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Jobs older than the window are not offered."""
    existing = make_work_item()
    WorkItem.objects.filter(pk=existing.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )

    with mock.patch("intake.chat.locate", return_value=NEAR_POTHOLE):
        assert nearby(client) == {"match": None}


def test_nearby_ignores_jobs_with_unknown_location(
    client: Client, make_work_item: Callable[..., WorkItem], settings: Settings
) -> None:
    """Jobs pinned at the depot (no real location) never match."""
    existing = make_work_item()
    depot = settings.FIELD_DEPOT
    WorkItem.objects.filter(pk=existing.pk).update(
        latitude=Decimal(str(depot["lat"])), longitude=Decimal(str(depot["lng"]))
    )
    at_depot = (Decimal(str(depot["lat"])), Decimal(str(depot["lng"])))

    with mock.patch("intake.chat.locate", return_value=at_depot):
        assert nearby(client) == {"match": None}


def test_nearby_without_coordinates_has_no_match(client: Client) -> None:
    """When the postcode can't be placed, the chat just carries on."""
    with mock.patch("intake.chat.locate", return_value=None):
        assert nearby(client) == {"match": None}


def test_nearby_unknown_category_has_no_match(client: Client) -> None:
    """Unknown categories are not looked up."""
    with mock.patch("intake.chat.locate") as locate_mock:
        assert nearby(client, category="nonsense") == {"match": None}
    locate_mock.assert_not_called()


def test_postcode_lookups_are_cached(settings: Settings) -> None:
    """The same postcode is only looked up once."""
    settings.POSTCODE_LOOKUP = True
    body = json.dumps({"result": {"latitude": 52.43, "longitude": -1.93}}).encode()
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = body
    cache.clear()
    with mock.patch(
        "intake.chat.urllib.request.urlopen", return_value=response
    ) as call:
        first = locate("B29 1AA")
        second = locate("b291aa")

    assert first == second
    assert call.call_count == 1
