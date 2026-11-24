"""Tests for configurable duplicate candidate discovery."""

from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from employees.work_models import WorkItem
from intake.models import ReportSubmission, TriagePolicy
from intake.services.duplicates import duplicate_candidates

pytestmark = pytest.mark.django_db


def report(latitude: str, longitude: str) -> ReportSubmission:
    """Create a report with a location."""
    return ReportSubmission.objects.create(
        description="A report",
        updates_requested=False,
        latitude=Decimal(latitude),
        longitude=Decimal(longitude),
    )


def activate_search_window(distance: int, age: int) -> None:
    """Set up an active policy for candidate lookup."""
    policy = TriagePolicy.objects.create(
        version=1, name="Test", duplicate_distance_m=distance, duplicate_age_days=age
    )
    TriagePolicy._base_manager.filter(pk=policy.pk).update(
        status="ACTIVE", activated_at=timezone.now()
    )


def test_window_finds_nearby_recent_items_and_filters_others(
    make_work_item: Callable[..., WorkItem],
) -> None:
    """Distance and creation age both bound the advisory candidate search."""
    activate_search_window(100, 30)
    submission = report("51.500000", "-0.120000")
    near = make_work_item()
    outside = make_work_item()
    outside.latitude = Decimal("51.510000")
    outside.save(update_fields=("latitude",))
    old = make_work_item()
    WorkItem.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )
    result = duplicate_candidates(submission)
    assert [candidate.work.pk for candidate in result.candidates] == [near.pk]
    assert result.distance_m == 100
    assert result.age_days == 30


def test_window_searches_across_antimeridian(
    make_work_item: Callable[..., WorkItem],
) -> None:
    """Nearby points on opposite sides of the dateline remain candidates."""
    activate_search_window(1000, 30)
    submission = report("0", "179.999000")
    work = make_work_item()
    work.latitude = Decimal("0")
    work.longitude = Decimal("-179.999000")
    work.save(update_fields=("latitude", "longitude"))
    result = duplicate_candidates(submission)
    assert [candidate.work.pk for candidate in result.candidates] == [work.pk]
    assert result.candidates[0].distance_m < 1000


def test_missing_window_falls_back_to_exact_pin(
    make_work_item: Callable[..., WorkItem],
) -> None:
    """No deployment-specific distance is assumed."""
    submission = report("51.500000", "-0.120000")
    work = make_work_item()
    nearby = make_work_item()
    nearby.longitude = Decimal("-0.120010")
    nearby.save(update_fields=("longitude",))
    result = duplicate_candidates(submission)
    assert [candidate.work.pk for candidate in result.candidates] == [work.pk]
    assert result.distance_m is None


def test_policy_requires_both_search_window_values() -> None:
    """A partially configured policy cannot be approved."""
    policy = TriagePolicy(version=1, name="Draft", duplicate_distance_m=100)
    with pytest.raises(ValidationError, match="both duplicate-search"):
        policy.full_clean()


def test_search_reports_truncated_candidate_pool(
    make_work_item: Callable[..., WorkItem],
) -> None:
    """A bounded search discloses when potentially relevant work was omitted."""
    activate_search_window(100, 30)
    submission = report("51.500000", "-0.120000")
    for _ in range(3):
        make_work_item()
    with patch("intake.services.duplicates.MAX_SEARCHED_CANDIDATES", 2):
        result = duplicate_candidates(submission)
    assert len(result.candidates) == 2
    assert result.truncated
