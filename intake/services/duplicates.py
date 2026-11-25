"""Human confirmation of duplicate report links."""

import math
from dataclasses import dataclass
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from employees.organisation_models import Employee
from employees.work_models import WorkItem
from intake.models import ReportSubmission, TriageAttempt, TriagePolicy

LINKABLE_STATUSES = (
    "SUBMITTED",
    "TRIAGED",
    "ASSIGNED",
    "IN_PROGRESS",
    "AWAITING_INFORMATION",
    "AWAITING_PARTS",
    "ON_HOLD",
    "RESOLVED",
)
EARTH_RADIUS_M = 6_371_008.8
MAX_SEARCHED_CANDIDATES = 500
MAX_DISPLAYED_CANDIDATES = 20


@dataclass(frozen=True)
class DuplicateCandidate:
    """A possible match and its approximate distance from the reported pin."""

    work: WorkItem
    distance_m: float


@dataclass(frozen=True)
class DuplicateSearch:
    """A bounded candidate list and the search window applied."""

    candidates: list[DuplicateCandidate]
    distance_m: int | None = None
    age_days: int | None = None
    truncated: bool = False


def exact_location_work_candidates(submission: ReportSubmission) -> QuerySet[WorkItem]:
    """Find work at the exact reported pin without deciding whether it matches."""
    if submission.latitude is None or submission.longitude is None:
        return WorkItem.objects.none()
    return (
        WorkItem.objects.filter(
            latitude=submission.latitude, longitude=submission.longitude
        )
        .select_related("status", "issue_type", "issue_type__department")
        .order_by("-created_at", "-pk")
    )


def duplicate_candidates(submission: ReportSubmission) -> DuplicateSearch:
    """Suggest nearby work using an approved window, or exact locations only."""
    if submission.latitude is None or submission.longitude is None:
        return DuplicateSearch([])
    policy = TriagePolicy.objects.filter(status=TriagePolicy.Status.ACTIVE).first()
    distance = policy.duplicate_distance_m if policy else None
    age = policy.duplicate_age_days if policy else None
    if (
        type(distance) is not int
        or type(age) is not int
        or not 1 <= distance <= 20_000_000
        or not 1 <= age <= 365_000
    ):
        exact_work = list(
            exact_location_work_candidates(submission)[: MAX_DISPLAYED_CANDIDATES + 1]
        )
        return DuplicateSearch(
            [
                DuplicateCandidate(item, 0)
                for item in exact_work[:MAX_DISPLAYED_CANDIDATES]
            ],
            truncated=len(exact_work) > MAX_DISPLAYED_CANDIDATES,
        )

    lat, lon = float(submission.latitude), float(submission.longitude)
    angular_distance = distance / EARTH_RADIUS_M
    latitude_delta = math.degrees(angular_distance)
    south, north = max(-90, lat - latitude_delta), min(90, lat + latitude_delta)
    work_query = WorkItem.objects.filter(
        latitude__gte=south,
        latitude__lte=north,
        created_at__gte=timezone.now() - timedelta(days=age),
    )
    if south > -90 and north < 90 and angular_distance < math.pi / 2:
        longitude_delta = math.degrees(
            math.asin(min(1, math.sin(angular_distance) / math.cos(math.radians(lat))))
        )
        west, east = lon - longitude_delta, lon + longitude_delta
        if west < -180:
            work_query = work_query.filter(
                Q(longitude__gte=west + 360) | Q(longitude__lte=east)
            )
        elif east > 180:
            work_query = work_query.filter(
                Q(longitude__gte=west) | Q(longitude__lte=east - 360)
            )
        else:
            work_query = work_query.filter(longitude__gte=west, longitude__lte=east)
    possible = list(
        work_query.select_related(
            "status", "issue_type", "issue_type__department"
        ).order_by("-created_at", "-pk")[: MAX_SEARCHED_CANDIDATES + 1]
    )
    candidates = []
    for work in possible[:MAX_SEARCHED_CANDIDATES]:
        lat_delta = math.radians(float(work.latitude) - lat)
        lon_delta = math.radians(float(work.longitude) - lon)
        a = (
            math.sin(lat_delta / 2) ** 2
            + math.cos(math.radians(lat))
            * math.cos(math.radians(float(work.latitude)))
            * math.sin(lon_delta / 2) ** 2
        )
        metres = 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1, a)))
        if metres <= distance:
            candidates.append(DuplicateCandidate(work, metres))
    candidates.sort(key=lambda candidate: candidate.distance_m)
    return DuplicateSearch(
        candidates[:MAX_DISPLAYED_CANDIDATES],
        distance_m=distance,
        age_days=age,
        truncated=(
            len(possible) > MAX_SEARCHED_CANDIDATES
            or len(candidates) > MAX_DISPLAYED_CANDIDATES
        ),
    )


@transaction.atomic
def link_duplicate(
    submission_id: int,
    *,
    reviewer: Employee,
    work_item_id: int,
    reason: str,
    confirmed_not_recurrence: bool = False,
) -> None:
    """Link a report only after an authorized reviewer confirms the match."""
    if reviewer.pk is None or not reviewer.user.has_perm(
        "intake.review_reportsubmission"
    ):
        raise ValidationError("An authorized reviewer is required.")
    if not reason.strip():
        raise ValidationError("A reason is required to link a duplicate.")
    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.triage_state == ReportSubmission.TriageState.DUPLICATE:
        if submission.work_item_id == work_item_id:
            return
        raise ValidationError("This report is already linked to different work.")
    if submission.triage_state != ReportSubmission.TriageState.NEEDS_REVIEW:
        raise ValidationError("Only reports in review can be linked as duplicates.")
    if submission.work_item_id is not None:
        raise ValidationError("This report is already linked to work.")
    work = (
        WorkItem.objects.select_for_update()
        .select_related("status")
        .filter(pk=work_item_id)
        .first()
    )
    if work is None or work.status.code not in LINKABLE_STATUSES:
        raise ValidationError("Choose eligible work that is not closed or cancelled.")
    if work.status.code == "RESOLVED" and confirmed_not_recurrence is not True:
        raise ValidationError(
            "Resolved work may be a recurrence; confirm it is the same issue."
        )
    submission.work_item = work
    submission.triage_state = ReportSubmission.TriageState.DUPLICATE
    submission.save(update_fields=("work_item", "triage_state"))
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.HUMAN,
        field_outcomes={"work_item_id": work.pk},
        evidence={
            "work_status": work.status.code,
            "possible_recurrence": work.status.code == "RESOLVED",
            "confirmed_not_recurrence": confirmed_not_recurrence,
        },
        decision=ReportSubmission.TriageState.DUPLICATE,
        reason=reason,
        reviewer=reviewer,
    )
