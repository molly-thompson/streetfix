"""Tests for the public report chat and its API."""

import json
import re
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any
from unittest import mock
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks, Settings

from employees.organisation_models import IssueType
from employees.work_models import WorkItem, WorkItemStatus
from intake.chat import locate
from intake.models import Reporter, ReportSubmission, TriageAttempt
from intake.services.rate_limit import REPORT_SUBMISSION
from intake.services.reference import display_reference, submission_for_reference

pytestmark = pytest.mark.django_db


def reference_of(work_item: WorkItem) -> str:
    """Create a report behind a work item and return its public reference."""
    submission = ReportSubmission.objects.create(
        work_item=work_item, updates_requested=False, description="An earlier report."
    )
    return display_reference(submission)


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


def test_report_is_saved_for_review_not_as_work(
    post_report: Callable[[dict[str, Any]], Any],
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A chat report waits for a reviewer; it never creates work itself."""
    with django_capture_on_commit_callbacks(execute=True):
        response = post_report(chat_report())

    assert response.status_code == 201
    assert not WorkItem.objects.exists()
    submission = ReportSubmission.objects.get()
    assert submission.work_item is None
    assert submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    assert submission.reported_issue_type is not None
    assert submission.reported_issue_type.code == "STREETLIGHT"
    assert submission.reported_time_sensitivity == "PROMPT"
    assert response.json() == {
        "reference": display_reference(submission),
        "status": "Received",
    }


def test_reference_is_random_and_reveals_nothing_about_the_report(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """References are not derived from IDs, and every report gets its own."""
    first = post_report(chat_report()).json()["reference"]
    second = post_report(chat_report()).json()["reference"]

    submissions = ReportSubmission.objects.order_by("pk")
    assert first != second
    assert str(submissions[0].pk) not in first.replace("-", "")
    assert re.fullmatch(r"[A-Z2-9]{4}-[A-Z2-9]{4}", first)


@override_settings(INTAKE_REFERENCE_PREFIX="REF-")
def test_reference_prefix_comes_from_configuration(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Deployments choose their own prefix, and lookups accept it or omit it."""
    reference = post_report(chat_report()).json()["reference"]

    assert reference.startswith("REF-")
    assert submission_for_reference(reference) == ReportSubmission.objects.get()
    assert submission_for_reference(reference.removeprefix("REF-").lower())


def test_ai_suggestion_is_kept_as_evidence_for_the_reviewer(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """The browser's priority is recorded as a suggestion, not applied."""
    post_report(chat_report())

    attempt = TriageAttempt.objects.get(stage=TriageAttempt.Stage.AI)
    assert attempt.decision == "SUGGESTED"
    assert attempt.field_outcomes["priority"] == {
        "state": "suggested",
        "value": "CRITICAL",
    }
    assert attempt.field_outcomes["urgency"]["value"] == "URGENT"
    assert attempt.evidence["priority_reasons"] == [
        'Raised to Urgent: "Wires hanging or exposed"'
    ]


def test_submission_keeps_the_reporters_account_for_the_reviewer(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """The submission has the reporter's words, location and language."""
    post_report(chat_report())

    text = ReportSubmission.objects.get().description
    assert "Wires hanging or exposed" in text
    assert "B29 1AA, Outside the Co-op" in text
    assert "Reported through the Polish chat." in text
    assert "needs confirming" not in text


def test_inactive_issue_type_goes_to_triage_desk(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """A category the team has switched off is no longer offered to reporters."""
    IssueType.objects.filter(code="POTHOLE").update(active=False)

    post_report(chat_report(case={"category": "pothole"}))

    issue = ReportSubmission.objects.get().reported_issue_type
    assert issue is not None
    assert issue.code == "OTHER"


def test_issue_types_are_never_created_by_a_report(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Reports use configured issue types, which keeps policy snapshots stable."""
    issue_types = IssueType.objects.count()

    post_report(chat_report(case={"category": "not-a-category"}))

    assert IssueType.objects.count() == issue_types
    issue = ReportSubmission.objects.get().reported_issue_type
    assert issue is not None
    assert issue.code == "OTHER"


def test_report_is_refused_when_no_issue_type_is_available(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """The chat never invents issue types to keep a report."""
    IssueType.objects.filter(code__in=("POTHOLE", "OTHER")).update(active=False)

    response = post_report(chat_report(case={"category": "pothole"}))

    assert response.status_code == 400
    assert not ReportSubmission.objects.exists()


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


def test_map_pin_takes_precedence_over_the_postcode(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """A pin chosen on the map is used without any postcode lookup."""
    with mock.patch("intake.chat.locate") as lookup:
        post_report(
            chat_report(
                case={
                    "location": {
                        "postcode": "B29 1AA",
                        "latitude": 51.5012,
                        "longitude": -0.1213,
                    }
                }
            )
        )

    lookup.assert_not_called()
    submission = ReportSubmission.objects.get()
    assert submission.latitude == Decimal("51.501200")
    assert submission.longitude == Decimal("-0.121300")


def test_postcode_is_looked_up_when_there_is_no_pin(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Without a pin the postcode gives an approximate location."""
    with mock.patch(
        "intake.chat.locate", return_value=(Decimal("52.1"), Decimal("-1.9"))
    ):
        post_report(chat_report())

    assert ReportSubmission.objects.get().latitude == Decimal("52.100000")


@pytest.mark.parametrize(
    "location",
    [
        {"description": "x", "latitude": 95, "longitude": 0},
        {"description": "x", "latitude": 51, "longitude": None},
        {"description": "x", "latitude": "nonsense", "longitude": "nonsense"},
    ],
)
def test_invalid_or_partial_pins_are_ignored(
    post_report: Callable[[dict[str, Any]], Any], location: dict[str, Any]
) -> None:
    """A bad pin never saves a half location or fails the whole report."""
    post_report(chat_report(case={"location": location}))

    submission = ReportSubmission.objects.get()
    assert submission.latitude is None
    assert submission.longitude is None


def test_unknown_location_is_flagged_not_guessed(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """Without coordinates the reviewer is told, and no depot pin is invented."""
    post_report(
        chat_report(
            case={"location": {"postcode": None, "description": "By the roundabout"}}
        )
    )

    submission = ReportSubmission.objects.get()
    assert "No map pin" in submission.description
    assert submission.latitude is None


def test_reporters_duplicate_claim_is_evidence_not_a_link(
    post_report: Callable[[dict[str, Any]], Any],
    make_work_item: Callable[..., WorkItem],
) -> None:
    """Only a reviewer can link a duplicate; the claim is recorded for them."""
    existing = make_work_item()
    earlier = ReportSubmission.objects.create(
        work_item=existing, updates_requested=False, description="First."
    )

    post_report(chat_report(case={"duplicate_of": display_reference(earlier)}))

    submission = ReportSubmission.objects.exclude(pk=earlier.pk).get()
    assert submission.work_item is None
    claim = TriageAttempt.objects.get(
        submission=submission, stage=TriageAttempt.Stage.AI
    ).evidence["reporter_duplicate_claim"]
    assert claim == {
        "reference": display_reference(earlier),
        "confirmed_by_reporter": True,
        "work_item_id": existing.pk,
    }
    assert WorkItem.objects.count() == 1


def test_unsure_duplicate_is_recorded_as_unconfirmed(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """A "not sure" answer is kept but not treated as a confirmation."""
    post_report(chat_report(case={"possible_duplicate_of": "ABCD-2345"}))

    claim = TriageAttempt.objects.get(stage=TriageAttempt.Stage.AI).evidence[
        "reporter_duplicate_claim"
    ]
    assert claim["confirmed_by_reporter"] is False
    assert claim["work_item_id"] is None


def test_photo_reference_is_required_to_be_verified(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """A chat report cannot claim photos that were never reserved and verified."""
    response = post_report(
        chat_report(case={"photo_draft": str(uuid4()), "photo_slots": [str(uuid4())]})
    )

    assert response.status_code == 400
    assert not ReportSubmission.objects.exists()


def test_more_than_one_chat_photo_is_rejected(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """The chat accepts a single photo."""
    response = post_report(
        chat_report(
            case={
                "photo_draft": str(uuid4()),
                "photo_slots": [str(uuid4()), str(uuid4())],
            }
        )
    )

    assert response.status_code == 400


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
    """A reviewer needs at least a postcode, a description or a pin."""
    response = post_report(
        chat_report(case={"location": {"postcode": None, "description": None}})
    )

    assert response.status_code == 400


def test_chat_reports_are_limited_per_address(
    post_report: Callable[[dict[str, Any]], Any],
) -> None:
    """An address over the hourly limit gets 429 and saves nothing more."""
    for _ in range(REPORT_SUBMISSION.limit):
        assert post_report(chat_report()).status_code == 201
    response = post_report(chat_report())

    assert response.status_code == 429
    assert ReportSubmission.objects.count() == REPORT_SUBMISSION.limit


def test_chat_and_form_share_one_limit(
    post_report: Callable[[dict[str, Any]], Any], client: Client
) -> None:
    """Switching between the chat and the form does not reset the limit."""
    with override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True):
        for _ in range(REPORT_SUBMISSION.limit):
            client.post(
                reverse("intake:submit_report"),
                {"other_selected": "on", "description": "An issue."},
            )

        assert post_report(chat_report()).status_code == 429


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


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (ReportSubmission.TriageState.RECEIVED, "Received"),
        (ReportSubmission.TriageState.NEEDS_REVIEW, "Under review"),
        (ReportSubmission.TriageState.OUT_OF_SCOPE, "Reviewed"),
    ],
)
def test_report_status_hides_review_decisions(
    client: Client, state: str, expected: str
) -> None:
    """Anyone with a reference sees progress, never decisions or personal details."""
    submission = ReportSubmission.objects.create(
        updates_requested=False, description="Private words.", triage_state=state
    )

    response = client.get(
        reverse("intake:report_status", args=[display_reference(submission)])
    )

    assert response.status_code == 200
    assert response.json() == {
        "reference": display_reference(submission),
        "status": expected,
        "issue": "",
    }


def test_report_status_follows_the_work_once_accepted(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """After acceptance the status is the work item's status."""
    submission = ReportSubmission.objects.create(
        work_item=make_work_item(),
        updates_requested=False,
        description="Words.",
        triage_state=ReportSubmission.TriageState.ACCEPTED,
    )

    response = client.get(
        reverse("intake:report_status", args=[display_reference(submission)])
    )

    assert response.json()["status"] == "Submitted"


@pytest.mark.parametrize("reference", ["SF-99999", "", "ZZZZ-ZZZZ", "A"])
def test_report_status_unknown_reference(client: Client, reference: str) -> None:
    """Unknown or malformed references return 404."""
    response = client.get(reverse("intake:report_status", args=[reference or "x"]))

    assert response.status_code == 404


def test_old_sequential_references_no_longer_resolve(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """References cannot be guessed by counting from a work item number."""
    work_item = make_work_item()
    ReportSubmission.objects.create(
        work_item=work_item, updates_requested=False, description="Words."
    )

    response = client.get(reverse("intake:report_status", args=[f"{work_item.pk:05d}"]))

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
    reference = reference_of(existing)

    with mock.patch("intake.chat.locate", return_value=NEAR_POTHOLE):
        result = nearby(client)

    assert result["match"]["reference"] == reference
    assert result["match"]["days_ago"] == 0


def test_nearby_ignores_jobs_with_no_public_report(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Work with no report behind it has no reference to offer the chat."""
    make_work_item()

    with mock.patch("intake.chat.locate", return_value=NEAR_POTHOLE):
        assert nearby(client) == {"match": None}


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
