"""Search the open issues the public may see, by plain-language query or map area.

Only an issue's type, status, age and approximate position are returned: no
references, descriptions, reporter details or photos.
"""

import math
import re
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal
from typing import Any

from django.db.models import Q
from django.utils import timezone

from employees.geo import distance_km
from employees.organisation_models import IssueType
from employees.work_models import WorkItem
from intake.chat import locate
from intake.models import IssueCategory
from site_settings.configuration import get_site_configuration

POSTCODE_IN_TEXT = re.compile(r"\b([A-Za-z]{1,2}\d[A-Za-z\d]?)\s*(\d[A-Za-z]{2})\b")
DISTANCE = re.compile(
    r"\bwithin\s+(\d+(?:\.\d+)?)\s*(km|kilometres?|kilometers?|miles?|mi|metres?|meters?|m)\b"
)
RECENT = re.compile(
    r"\b(?:in\s+the\s+)?(?:last|past)\s+(\d+|a|an|one)?\s*"
    r"(day|week|month|year)s?\b"
)
TODAY = re.compile(r"\b(today|this\s+week|this\s+month)\b")
UNIT_DAYS = {"day": 1, "week": 7, "month": 30, "year": 365}
THIS_PERIOD_DAYS = {"today": 1, "this week": 7, "this month": 30}
COORDINATE_PRECISION = 4  # about 10 metres


@dataclass
class SearchCriteria:
    """What a search is looking for, with notes on what was understood."""

    issue_type_ids: set[int] = field(default_factory=set)
    issue_type_names: list[str] = field(default_factory=list)
    center: tuple[float, float] | None = None
    radius_km: float | None = None
    bounds: tuple[float, float, float, float] | None = None
    max_age_days: int | None = None
    understood: list[str] = field(default_factory=list)
    place_missing: bool = False


@dataclass(frozen=True)
class PublicIssue:
    """One open issue as shown to the public."""

    id: int
    issue: str
    category: str
    status: str
    days_open: int
    latitude: float
    longitude: float
    distance_km: float | None


@dataclass(frozen=True)
class SearchResult:
    """Matching open issues and how the query was understood."""

    issues: list[PublicIssue]
    truncated: bool
    understood: list[str]
    place_missing: bool

    def as_json(self) -> dict[str, Any]:
        """Return a browser-safe representation."""
        return {
            "issues": [
                {
                    "id": issue.id,
                    "issue": issue.issue,
                    "category": issue.category,
                    "status": issue.status,
                    "days_open": issue.days_open,
                    "latitude": issue.latitude,
                    "longitude": issue.longitude,
                    "distance_km": issue.distance_km,
                }
                for issue in self.issues
            ],
            "truncated": self.truncated,
            "understood": self.understood,
            "place_missing": self.place_missing,
        }


def _unit_km(unit: str) -> float:
    """Return how many kilometres one of the given distance unit is."""
    if unit.startswith("mi"):
        return 1.609344
    if unit.startswith("k"):
        return 1.0
    return 0.001


def _words(text: str) -> str:
    """Lower-case words with simple plurals removed, padded for whole-word tests."""
    words = [
        word[:-1] if len(word) > 3 and word.endswith("s") else word
        for word in re.findall(r"[a-z0-9]+", text.lower())
    ]
    return f" {' '.join(words)} "


def _matching_issue_types(text: str) -> list[IssueType]:
    """Find issue types named in the text, by name, keyword or sub-issue."""
    padded = _words(text)
    issue_types = list(
        IssueType.objects.filter(active=True).select_related("parent", "chat_category")
    )
    categories = {
        category.issue_type_id: category
        for category in IssueCategory.objects.filter(
            active=True, issue_type__isnull=False
        ).prefetch_related("subcategories", "keywords")
    }
    named = set()
    for issue_type in issue_types:
        labels = [issue_type.name]
        category = categories.get(issue_type.pk)
        if category is not None:
            labels += [sub.label for sub in category.subcategories.all() if sub.active]
            for keyword in category.keywords.all():
                if not keyword.active:
                    continue
                try:
                    if re.search(keyword.pattern, text, re.IGNORECASE):
                        named.add(issue_type.pk)
                except re.error:
                    continue
        if any(_words(label).strip() and _words(label) in padded for label in labels):
            named.add(issue_type.pk)
    # A named category stands for every issue type inside it.
    selected = [
        issue_type
        for issue_type in issue_types
        if issue_type.kind == IssueType.Kind.ISSUE
        and (issue_type.pk in named or issue_type.parent_id in named)
    ]
    return selected


def parse_query(text: str) -> SearchCriteria:
    """Understand a plain-language search such as "potholes within 1 mile of B1 1AA"."""
    criteria = SearchCriteria()
    configuration = get_site_configuration()
    remaining = text.strip()[:300]
    lowered = remaining.lower()

    match = DISTANCE.search(lowered)
    if match:
        unit = match.group(2)
        factor = _unit_km(unit)
        criteria.radius_km = float(match.group(1)) * factor
        criteria.understood.append(f"within {match.group(1)} {unit}")

    match = RECENT.search(lowered)
    if match:
        count = match.group(1)
        number = int(count) if count and count.isdigit() else 1
        criteria.max_age_days = number * UNIT_DAYS[match.group(2)]
        criteria.understood.append(f"reported in the last {criteria.max_age_days} days")
    else:
        match = TODAY.search(lowered)
        if match:
            criteria.max_age_days = THIS_PERIOD_DAYS[
                re.sub(r"\s+", " ", match.group(1))
            ]
            criteria.understood.append(match.group(1))

    postcode = POSTCODE_IN_TEXT.search(remaining)
    if postcode:
        found = locate("".join(postcode.groups()))
        if found is None:
            criteria.place_missing = True
        else:
            criteria.center = (float(found[0]), float(found[1]))
            if criteria.radius_km is None:
                criteria.radius_km = float(configuration.public_search_radius_km)
            criteria.understood.append(f"near {postcode.group(0).upper()}")
        # Keep the postcode out of the issue-type wording.
        lowered_text = remaining.replace(postcode.group(0), " ")
    else:
        lowered_text = remaining

    for issue_type in _matching_issue_types(lowered_text):
        criteria.issue_type_ids.add(issue_type.pk)
        criteria.issue_type_names.append(issue_type.name)
    if criteria.issue_type_names:
        criteria.understood.insert(0, ", ".join(sorted(set(criteria.issue_type_names))))
    return criteria


def _bounds_filter(
    center: tuple[float, float] | None,
    radius_km: float | None,
    bounds: tuple[float, float, float, float] | None,
) -> Q:
    query = Q()
    if center is not None and radius_km is not None:
        lat_margin = radius_km / 110.574
        lng_margin = radius_km / (
            111.320 * max(math.cos(math.radians(center[0])), 0.01)
        )
        query &= Q(latitude__range=(center[0] - lat_margin, center[0] + lat_margin))
        query &= Q(longitude__range=(center[1] - lng_margin, center[1] + lng_margin))
    if bounds is not None:
        south, west, north, east = bounds
        query &= Q(latitude__range=(south, north), longitude__range=(west, east))
    return query


def search_open_issues(criteria: SearchCriteria) -> SearchResult:
    """Return open issues matching the criteria, nearest or newest first."""
    configuration = get_site_configuration()
    now = timezone.now()
    window = configuration.public_search_window_days
    if criteria.max_age_days is not None:
        window = min(window, criteria.max_age_days)
    queryset = (
        WorkItem.objects.filter(
            status__is_resolved=False,
            status__is_ended=False,
            status__is_cancelled=False,
            created_at__gte=now - timedelta(days=window),
            issue_type__kind=IssueType.Kind.ISSUE,
            issue_type__active=True,
        )
        .exclude(
            latitude=Decimal(configuration.depot_latitude).quantize(
                Decimal("0.000001")
            ),
            longitude=Decimal(configuration.depot_longitude).quantize(
                Decimal("0.000001")
            ),
        )
        .filter(_bounds_filter(criteria.center, criteria.radius_km, criteria.bounds))
        .select_related("status", "issue_type__parent")
    )
    if criteria.issue_type_ids:
        queryset = queryset.filter(issue_type_id__in=criteria.issue_type_ids)
    issues = []
    for item in queryset.order_by("-created_at"):
        lat, lng = float(item.latitude), float(item.longitude)
        distance = None
        if criteria.center is not None:
            distance = distance_km(*criteria.center, lat, lng)
            if criteria.radius_km is not None and distance > criteria.radius_km:
                continue
        parent = item.issue_type.parent
        issues.append(
            PublicIssue(
                id=item.pk,
                issue=item.issue_type.name,
                category=parent.name if parent else "",
                status=str(item.status.label),
                days_open=(now - item.created_at).days,
                latitude=round(lat, COORDINATE_PRECISION),
                longitude=round(lng, COORDINATE_PRECISION),
                distance_km=round(distance, 2) if distance is not None else None,
            )
        )
    if criteria.center is not None:
        issues.sort(key=lambda issue: issue.distance_km or 0)
    limit = configuration.public_search_max_results
    return SearchResult(
        issues=issues[:limit],
        truncated=len(issues) > limit,
        understood=criteria.understood,
        place_missing=criteria.place_missing,
    )
