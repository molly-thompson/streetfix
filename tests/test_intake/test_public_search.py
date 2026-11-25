"""Tests for public search of open issues."""

from collections.abc import Callable, Iterator
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from employees.organisation_models import IssueType
from employees.work_models import WorkItem, WorkItemStatus
from intake.models import IssueCategory, IssueCategoryKeyword
from site_settings.configuration import clear_site_configuration_cache
from site_settings.models import SiteConfiguration

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def fresh_configuration() -> Iterator[None]:
    """Keep cached site configuration from leaking between tests."""
    clear_site_configuration_cache()
    yield
    clear_site_configuration_cache()


API = "intake:search_issues_api"


def _search(client: Client, **params: str) -> dict:  # type: ignore[type-arg]
    response = client.get(reverse(API), params)
    assert response.status_code == 200, response.content
    return response.json()  # type: ignore[no-any-return]


def _place(item: WorkItem, lat: str, lng: str) -> WorkItem:
    item.latitude, item.longitude = Decimal(lat), Decimal(lng)
    item.save()
    return item


def test_only_open_issues_are_found(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Resolved work is left out and no references or descriptions are shown."""
    open_item = make_work_item("POTHOLE")
    done = make_work_item("POTHOLE")
    done.status = WorkItemStatus.objects.get(is_resolved=True)
    done.save()
    data = _search(client)
    assert [issue["id"] for issue in data["issues"]] == [open_item.pk]
    assert set(data["issues"][0]) == {
        "id",
        "issue",
        "category",
        "status",
        "days_open",
        "latitude",
        "longitude",
        "distance_km",
    }


def test_natural_language_matches_issue_type_and_plural(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Asking for "potholes" finds the Pothole issue type only."""
    make_work_item("POTHOLE")
    make_work_item("STREETLIGHT")
    data = _search(client, q="any potholes near me?")
    assert [issue["issue"] for issue in data["issues"]] == ["Pothole"]
    assert "Pothole" in data["understood"][0]


def test_keywords_configured_in_the_database_are_used(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Chat category keywords also drive the search."""
    item = make_work_item("STREETLIGHT")
    category = IssueCategory.objects.create(
        code="lights",
        label="Lights",
        issue_type=item.issue_type,
        department_name="Roads",
        issue_type_code="STREETLIGHT",
        issue_type_name="Streetlight",
    )
    IssueCategoryKeyword.objects.create(category=category, pattern=r"dark|lamp")
    make_work_item("POTHOLE")
    data = _search(client, q="the lamp is out")
    assert [issue["id"] for issue in data["issues"]] == [item.pk]


def test_postcode_and_distance_in_the_query(
    client: Client,
    make_work_item: Callable[..., WorkItem],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A postcode and "within" distance limit results to that area, nearest first."""
    monkeypatch.setattr(
        "intake.services.public_search.locate",
        lambda postcode: (Decimal("51.5"), Decimal("-0.12")),
    )
    near = _place(make_work_item(), "51.5010", "-0.1200")
    nearer = _place(make_work_item(), "51.5002", "-0.1200")
    _place(make_work_item(), "51.6000", "-0.1200")
    data = _search(client, q="potholes within 500 m of SW1A 1AA")
    assert [issue["id"] for issue in data["issues"]] == [nearer.pk, near.pk]
    assert data["issues"][0]["distance_km"] < data["issues"][1]["distance_km"]


def test_unknown_postcode_is_reported(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    make_work_item: Callable[..., WorkItem],
) -> None:
    """When a postcode cannot be located, the search says so."""
    monkeypatch.setattr("intake.services.public_search.locate", lambda postcode: None)
    make_work_item()
    assert _search(client, q="SW1A 1AA")["place_missing"] is True


def test_map_area_filter(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Only issues inside the visible map bounds are returned."""
    inside = _place(make_work_item(), "51.5", "-0.12")
    _place(make_work_item(), "52.5", "-1.9")
    data = _search(client, south="51.4", west="-0.2", north="51.6", east="-0.1")
    assert [issue["id"] for issue in data["issues"]] == [inside.pk]


def test_old_issues_and_result_cap_come_from_configuration(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """The result cap is configurable and flags truncation."""
    SiteConfiguration.objects.update_or_create(
        pk=1, defaults={"public_search_max_results": 1}
    )
    make_work_item()
    make_work_item()
    data = _search(client)
    assert len(data["issues"]) == 1
    assert data["truncated"] is True


def test_invalid_parameters_are_rejected(client: Client) -> None:
    """Bad coordinates or incomplete bounds return a client error."""
    url = reverse(API)
    assert client.get(url, {"lat": "abc", "lng": "1"}).status_code == 400
    assert client.get(url, {"lat": "10"}).status_code == 400
    assert client.get(url, {"south": "1"}).status_code == 400


def test_search_can_be_switched_off(client: Client) -> None:
    """Organisations can disable public search from the site configuration."""
    SiteConfiguration.objects.update_or_create(
        pk=1, defaults={"public_search_enabled": False}
    )
    assert client.get(reverse(API)).status_code == 404
    assert client.get(reverse("intake:search_issues")).status_code == 404


def test_category_name_includes_its_issue_types(
    client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Naming a category finds issue types inside it."""
    item = make_work_item("POTHOLE")
    category = IssueType.objects.create(
        kind=IssueType.Kind.CATEGORY, name="Road surface", code="SURFACE"
    )
    item.issue_type.parent = category
    item.issue_type.save()
    data = _search(client, q="road surface problems")
    assert [issue["id"] for issue in data["issues"]] == [item.pk]
    assert data["issues"][0]["category"] == "Road surface"


def test_search_page_renders(client: Client) -> None:
    """The page loads without a map provider configured."""
    response = client.get(reverse("intake:search_issues"))
    assert response.status_code == 200
    assert b"issue-search-form" in response.content
