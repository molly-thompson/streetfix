"""Tests for the public report tracking dashboard."""

from collections.abc import Callable, Iterator

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from employees.work_models import WorkItem, WorkItemStatus
from intake.models import ReportSubmission
from site_settings.configuration import clear_site_configuration_cache
from site_settings.models import SiteConfiguration

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_configuration() -> Iterator[None]:
    """Keep cached site configuration from leaking between tests."""
    clear_site_configuration_cache()
    yield
    clear_site_configuration_cache()


def _submission(work_item: WorkItem | None = None) -> ReportSubmission:
    return ReportSubmission.objects.create(
        updates_requested=False,
        description="Secret detail",
        work_item=work_item,
        triage_state=ReportSubmission.TriageState.NEEDS_REVIEW,
    )


def _reference(submission: ReportSubmission) -> str:
    code = submission.public_reference
    return f"{code[:4]}-{code[4:]}"


def test_reporter_can_follow_a_report_by_reference(client: Client) -> None:
    """A typed reference is remembered and shows its public status only."""
    submission = _submission()
    url = reverse("intake:track_reports")
    response = client.post(
        url, {"action": "add", "reference": _reference(submission)}, follow=True
    )
    assert _reference(submission).encode() in response.content
    assert b"Under review" in response.content
    assert b"Secret detail" not in response.content
    assert _reference(submission).encode() in client.get(url).content


def test_unknown_reference_is_rejected(client: Client) -> None:
    """A made-up reference adds nothing."""
    response = client.post(
        reverse("intake:track_reports"),
        {"action": "add", "reference": "ZZZZ-ZZZZ"},
        follow=True,
    )
    assert b"could not add" in response.content
    assert b"not following any reports" in response.content


def test_other_browsers_do_not_see_followed_reports(client: Client) -> None:
    """The list belongs to the browser session that followed the report."""
    submission = _submission()
    client.post(
        reverse("intake:track_reports"),
        {"action": "add", "reference": _reference(submission)},
    )
    assert (
        _reference(submission).encode()
        not in Client().get(reverse("intake:track_reports")).content
    )


def test_status_follows_the_work_item(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Progress on the linked work item shows up on the dashboard."""
    item = make_work_item()
    submission = _submission(item)
    url = reverse("intake:track_reports")
    client.post(url, {"action": "add", "reference": _reference(submission)})
    item.status = WorkItemStatus.objects.get(is_resolved=True)
    item.save()
    assert item.status.label.encode() in client.get(url).content


def test_report_can_be_removed(client: Client) -> None:
    """Removing a report stops it appearing in the browser's list."""
    submission = _submission()
    url = reverse("intake:track_reports")
    data = {"reference": _reference(submission)}
    client.post(url, {"action": "add", **data})
    client.post(url, {"action": "remove", **data})
    assert _reference(submission).encode() not in client.get(url).content


def test_following_is_limited_by_configuration(client: Client) -> None:
    """The cap on followed reports comes from the site configuration."""
    SiteConfiguration.objects.update_or_create(
        pk=1, defaults={"public_tracking_max_reports": 1}
    )
    url = reverse("intake:track_reports")
    first, second = _submission(), _submission()
    client.post(url, {"action": "add", "reference": _reference(first)})
    client.post(url, {"action": "add", "reference": _reference(second)})
    content = client.get(url).content
    assert _reference(first).encode() in content
    assert _reference(second).encode() not in content


def test_dashboard_can_be_switched_off(client: Client) -> None:
    """Organisations can disable tracking from the site configuration."""
    SiteConfiguration.objects.update_or_create(
        pk=1, defaults={"public_tracking_enabled": False}
    )
    assert client.get(reverse("intake:track_reports")).status_code == 404
    assert b"Track a report" not in client.get("/").content


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=True)
def test_submitted_report_is_followed_automatically(client: Client) -> None:
    """A report sent from this browser appears without typing the reference."""
    client.post(
        reverse("intake:submit_report"),
        {"other_selected": "on", "description": "An issue."},
    )
    submission = ReportSubmission.objects.get()
    assert (
        _reference(submission).encode()
        in client.get(reverse("intake:track_reports")).content
    )
