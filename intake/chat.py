"""Turn a report from the public chat into a submission awaiting review.

The chat (``static/js/report-chat.js``) does a first rules-based pass in the
browser: it suggests a category, priority and team, and explains why. This
module records that suggestion as an AI-stage triage attempt next to the
reporter's own evidence, and saves everything through the shared submission
service. Nothing here creates work: a person reviews every report.
"""

import json
import logging
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from employees.geo import distance_km
from employees.organisation_models import IssueType
from employees.work_models import WorkItem
from intake.models import (
    ContactMethod,
    IssueCategory,
    Reporter,
    ReportSubmission,
    TriageAttempt,
)
from intake.services.reference import submission_for_reference
from intake.services.submission import submit_report
from site_settings.configuration import get_site_configuration

logger = logging.getLogger(__name__)

POSTCODES_IO_URL = "https://api.postcodes.io/postcodes/"
UK_POSTCODE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?) ?(\d[A-Z]{2})$")

# A report counts as a possible duplicate of an open job of the same issue
# type this close by, reported this recently.
FINISHED_STATUSES = ("RESOLVED", "CLOSED", "CANCELLED")
MAX_CHAT_PHOTOS = 1

# Chat priority levels follow the brief's SLA table.
PRIORITY_CODES = {
    "Urgent": "CRITICAL",
    "High": "HIGH",
    "Medium": "NORMAL",
    "Low": "LOW",
}
URGENCY_CODES = {
    "Urgent": "EMERGENCY",
    "High": "URGENT",
    "Medium": "SOON",
    "Low": "ROUTINE",
}
# What the reporter said about timing, recorded as evidence and never as a decision.
TIME_SENSITIVITY = {
    "Urgent": ReportSubmission.ReportedTimeSensitivity.IMMEDIATE,
    "High": ReportSubmission.ReportedTimeSensitivity.PROMPT,
    "Medium": ReportSubmission.ReportedTimeSensitivity.NEAR_TERM,
    "Low": ReportSubmission.ReportedTimeSensitivity.ROUTINE,
}
CONTACT_CODES = {
    "Email": "EMAIL",
    "Text message": "TELEPHONE",
    "Phone call": "TELEPHONE",
}


@dataclass(frozen=True)
class ChatReport:
    """A validated report from the chat."""

    category: str
    issue_type_id: int | None
    other_selected: bool
    sub_issue: str
    description: str
    category_source: str
    chat_language: str
    priority: str
    reporter_urgency: str
    priority_reasons: list[str]
    postcode: str
    location_description: str
    latitude: Decimal | None
    longitude: Decimal | None
    duplicate_of: str
    possible_duplicate_of: str
    photo_draft_id: UUID | None
    photo_slot_ids: list[UUID]
    wants_updates: bool
    name: str
    email: str
    phone: str
    preferred_contact: str
    preferred_language: str


def _text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if isinstance(value, str | int | float) else ""


def _coordinate(value: Any, limit: int) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        number = Decimal(str(value)).quantize(Decimal("0.000001"))
    except InvalidOperation:
        return None
    return number if number.is_finite() and abs(number) <= limit else None


def _uuid(value: Any) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


def parse_issue_type_id(value: Any) -> int:
    """Validate an issue identifier without coercing floats or overflowing the DB."""
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValidationError("This kind of report is not available right now.")
    if isinstance(value, str) and (
        len(value) > 19 or not (value.isascii() and value.isdecimal())
    ):
        raise ValidationError("This kind of report is not available right now.")
    issue_type_id = int(value)
    if not 0 < issue_type_id <= 9223372036854775807:
        raise ValidationError("This kind of report is not available right now.")
    return issue_type_id


def parse_report(body: bytes) -> ChatReport:
    """Validate the chat's JSON and return a report.

    Raises:
        ValidationError: If the body is not a usable report.
    """
    try:
        data = json.loads(body)
        case = data["case"]
        reporter = data.get("reporter") or {}
        location = case.get("location") or {}
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValidationError("The report could not be read.") from error
    if (
        not isinstance(case, dict)
        or not isinstance(reporter, dict)
        or not isinstance(location, dict)
    ):
        raise ValidationError("The report could not be read.")

    category = _text(case.get("category"), 40)
    issue_type_id = None
    other_selected = case.get("other_selected") is True
    if "issue_type_id" in case:
        raw_issue_type_id = case["issue_type_id"]
        if "other_selected" in case and not isinstance(case["other_selected"], bool):
            raise ValidationError("Choose an issue or select Other.")
        if raw_issue_type_id is not None:
            if other_selected:
                raise ValidationError("This kind of report is not available right now.")
            issue_type_id = parse_issue_type_id(raw_issue_type_id)
            if _offered_issue_type_id(issue_type_id) is None:
                raise ValidationError("This kind of report is not available right now.")
        elif not other_selected:
            raise ValidationError("Choose an issue or select Other.")
    elif _offered_issue_type(category) is None:
        category = "other"
    priority = _text(case.get("priority_suggested"), 10)
    if priority not in PRIORITY_CODES:
        priority = "Medium"
    reporter_urgency = _text(case.get("reporter_urgency"), 10)
    reasons = case.get("priority_reasons")
    postcode = _text(location.get("postcode"), 10).upper()
    location_description = _text(location.get("description"), 200)
    latitude = _coordinate(location.get("latitude"), 90)
    longitude = _coordinate(location.get("longitude"), 180)
    if latitude is None or longitude is None:
        latitude = longitude = None
    if not postcode and not location_description and latitude is None:
        raise ValidationError(
            "A postcode, a description of the location or a map pin is needed."
        )
    wants_updates = reporter.get("wants_updates") is True
    raw_slots = case.get("photo_slots")
    slots = [_uuid(value) for value in raw_slots] if isinstance(raw_slots, list) else []
    if None in slots or len(slots) > MAX_CHAT_PHOTOS:
        raise ValidationError("A photo reference was not recognised.")

    return ChatReport(
        category=category,
        issue_type_id=issue_type_id,
        other_selected=other_selected,
        sub_issue=_text(case.get("sub_issue"), 200),
        description=_text(case.get("description"), 1000),
        category_source=_text(case.get("category_source"), 60),
        chat_language=_text(case.get("chat_language"), 40),
        priority=priority,
        reporter_urgency=reporter_urgency if reporter_urgency in URGENCY_CODES else "",
        priority_reasons=[_text(r, 200) for r in reasons][:10]
        if isinstance(reasons, list)
        else [],
        postcode=postcode,
        location_description=location_description,
        latitude=latitude,
        longitude=longitude,
        duplicate_of=_text(case.get("duplicate_of"), 24),
        possible_duplicate_of=_text(case.get("possible_duplicate_of"), 24),
        photo_draft_id=_uuid(case.get("photo_draft")),
        photo_slot_ids=[slot for slot in slots if slot is not None],
        wants_updates=wants_updates,
        name=_text(reporter.get("name"), 150) if wants_updates else "",
        email=_text(reporter.get("email"), 254) if wants_updates else "",
        phone=_text(reporter.get("phone"), 40) if wants_updates else "",
        preferred_contact=_text(reporter.get("preferred_contact"), 20),
        preferred_language=_text(reporter.get("preferred_language"), 40),
    )


def _offered_issue_type(category: str) -> IssueType | None:
    """Resolve legacy chat category keys through their configured mapping."""
    category_config = (
        IssueCategory.objects.filter(code=category, active=True)
        .select_related("issue_type")
        .first()
    )
    if category_config is None or category_config.issue_type_id is None:
        return None
    return _offered_issue_type_id(category_config.issue_type_id)


def _offered_issue_type_id(issue_type_id: int) -> IssueType | None:
    return IssueType.objects.filter(
        pk=issue_type_id,
        kind=IssueType.Kind.ISSUE,
        department__isnull=False,
        active=True,
    ).first()


def _issue_type(report: ChatReport) -> IssueType | None:
    if report.other_selected and report.issue_type_id is None:
        return None
    issue_type = (
        _offered_issue_type_id(report.issue_type_id)
        if report.issue_type_id is not None
        else _offered_issue_type(report.category)
    )
    if issue_type is None:
        raise ValidationError("This kind of report is not available right now.")
    return issue_type


def locate(postcode: str) -> tuple[Decimal, Decimal] | None:
    """Return the latitude and longitude of a UK postcode from postcodes.io."""
    match = UK_POSTCODE.match(postcode.replace(" ", "").upper())
    if not match or not settings.POSTCODE_LOOKUP:
        return None
    postcode = match.group(1) + match.group(2)
    cache_key = f"intake:postcode:{postcode}"
    cached = cache.get(cache_key)
    if cached is not None:
        return Decimal(cached[0]), Decimal(cached[1])
    url = POSTCODES_IO_URL + urllib.parse.quote(postcode)
    try:
        with urllib.request.urlopen(url, timeout=4) as response:  # noqa: S310 (fixed https URL)
            result = json.load(response)["result"]
        coordinates = (
            Decimal(str(result["latitude"])).quantize(Decimal("0.000001")),
            Decimal(str(result["longitude"])).quantize(Decimal("0.000001")),
        )
    except OSError, ValueError, KeyError, TypeError:
        logger.warning("Postcode lookup failed for %s", postcode)
        return None
    cache.set(
        cache_key,
        (str(coordinates[0]), str(coordinates[1])),
        get_site_configuration().postcode_cache_seconds,
    )
    return coordinates


def nearby_open_work(
    category: str, postcode: str, *, issue_type_id: int | None = None
) -> WorkItem | None:
    """Return the closest open work item that may be the same problem.

    Matches the same issue type within the configured duplicate radius of the
    postcode, reported in the configured duplicate window. Work items
    pinned at the depot (location unknown) are never matched, because their
    pin is not where the problem is.
    """
    issue_type = (
        _offered_issue_type_id(issue_type_id)
        if issue_type_id is not None
        else _offered_issue_type(category)
    )
    if issue_type is None:
        return None
    coordinates = locate(postcode)
    if coordinates is None:
        return None
    lat, lng = float(coordinates[0]), float(coordinates[1])
    configuration = get_site_configuration()
    depot = {
        "lat": float(configuration.depot_latitude),
        "lng": float(configuration.depot_longitude),
        "name": configuration.depot_name,
    }
    margin = configuration.duplicate_radius_km / Decimal("110")
    candidates = (
        WorkItem.objects.filter(
            issue_type=issue_type,
            created_at__gte=timezone.now()
            - timedelta(days=configuration.duplicate_window_days),
            latitude__range=(coordinates[0] - margin, coordinates[0] + margin),
        )
        .exclude(status__code__in=FINISHED_STATUSES)
        .exclude(
            latitude=Decimal(str(depot["lat"])).quantize(Decimal("0.000001")),
            longitude=Decimal(str(depot["lng"])).quantize(Decimal("0.000001")),
        )
    )
    best: tuple[float, WorkItem] | None = None
    for item in candidates:
        distance = distance_km(lat, lng, float(item.latitude), float(item.longitude))
        if distance <= float(configuration.duplicate_radius_km) and (
            best is None or distance < best[0]
        ):
            best = (distance, item)
    return best[1] if best else None


def _submission_text(report: ChatReport, issue_name: str, has_pin: bool) -> str:
    """Write the submission so a reviewer has the reporter's account in one place."""
    lines = [report.sub_issue or issue_name]
    if report.description:
        lines.append(f"Reporter's words: {report.description}")
    where = ", ".join(p for p in (report.postcode, report.location_description) if p)
    if where:
        lines.append(f"Location: {where}")
    if not has_pin:
        lines.append("No map pin: confirm the location from the description.")
    if report.chat_language and report.chat_language != "English":
        lines.append(f"Reported through the {report.chat_language} chat.")
    if report.preferred_language:
        lines.append(f"Preferred language for updates: {report.preferred_language}")
    return "\n".join(lines)


def _duplicate_claim(reference: str, *, confirmed: bool) -> dict[str, Any]:
    """Record what the reporter said about a possible duplicate, unverified."""
    other = submission_for_reference(reference)
    return {
        "reference": reference,
        "confirmed_by_reporter": confirmed,
        "work_item_id": other.work_item_id if other is not None else None,
    }


def _contact(report: ChatReport) -> tuple[Reporter | None, ContactMethod | None]:
    if not (report.wants_updates and (report.email or report.phone)):
        return None, None
    reporter = Reporter.objects.create(
        name=report.name, email=report.email, telephone=report.phone
    )
    code = CONTACT_CODES.get(report.preferred_contact, "EMAIL")
    if code == "EMAIL" and not report.email:
        code = "TELEPHONE"
    elif code == "TELEPHONE" and not report.phone:
        code = "EMAIL"
    return reporter, ContactMethod.objects.get(code=code)


@transaction.atomic
def submit_chat_report(
    report: ChatReport, *, session_key: str = ""
) -> ReportSubmission:
    """Save a chat report for review, with its suggestions kept as evidence."""
    issue_type = _issue_type(report)
    latitude, longitude = report.latitude, report.longitude
    if latitude is None and report.postcode:
        found = locate(report.postcode)
        latitude, longitude = found if found is not None else (None, None)
    reporter, method = _contact(report)
    time_sensitivity = TIME_SENSITIVITY.get(
        report.reporter_urgency, ReportSubmission.ReportedTimeSensitivity.UNKNOWN
    )
    submission = submit_report(
        ReportSubmission(
            reporter=reporter,
            contact_method=method,
            updates_requested=reporter is not None,
            description=_submission_text(
                report, issue_type.name if issue_type else "Other", latitude is not None
            ),
            reported_issue_type=issue_type,
            other_selected=report.other_selected,
            location_description=report.location_description,
            reported_time_sensitivity=time_sensitivity,
            latitude=latitude,
            longitude=longitude,
        ),
        photo_draft_id=report.photo_draft_id,
        photo_slot_ids=report.photo_slot_ids,
        session_key=session_key,
    )
    evidence: dict[str, Any] = {
        "source": "browser rules",
        "category_source": report.category_source,
        "priority_reasons": report.priority_reasons,
        "chat_language": report.chat_language,
    }
    if report.duplicate_of:
        evidence["reporter_duplicate_claim"] = _duplicate_claim(
            report.duplicate_of, confirmed=True
        )
    elif report.possible_duplicate_of:
        evidence["reporter_duplicate_claim"] = _duplicate_claim(
            report.possible_duplicate_of, confirmed=False
        )
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.AI,
        field_outcomes={
            "priority": {
                "state": "suggested",
                "value": PRIORITY_CODES[report.priority],
            },
            "urgency": {
                "state": "suggested",
                "value": URGENCY_CODES[report.reporter_urgency or report.priority],
            },
        },
        evidence=evidence,
        decision="SUGGESTED",
        reason="Suggestion made in the browser; a reviewer must confirm it.",
    )
    return submission
