"""Turn a report from the public chat into work items and submissions.

The chat (``static/js/report-chat.js``) does the first triage in the browser:
it suggests a category, priority and team, and explains why. This module
stores that suggestion. A work item always starts as ``SUBMITTED``, so a
triage officer still confirms it before anything is decided.
"""

import base64
import binascii
import json
import logging
import re
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from typing import Any

import cloudinary.exceptions
import cloudinary.uploader
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from employees.geo import distance_km
from employees.organisation_models import IssueType
from employees.work_models import Priority, Urgency, WorkItem, WorkItemStatus
from intake.models import (
    ContactMethod,
    Reporter,
    ReportSubmission,
    ReportSubmissionPhoto,
)

logger = logging.getLogger(__name__)

REFERENCE_PREFIX = "SF-"
MAX_PHOTO_BYTES = 5 * 1024 * 1024
POSTCODES_IO_URL = "https://api.postcodes.io/postcodes/"
UK_POSTCODE = re.compile(r"^([A-Z]{1,2}\d[A-Z\d]?) ?(\d[A-Z]{2})$")

# A report counts as a possible duplicate of an open job of the same issue
# type this close by, reported this recently.
DUPLICATE_RADIUS_KM = 0.2
DUPLICATE_WINDOW_DAYS = 30
FINISHED_STATUSES = ("RESOLVED", "CLOSED", "CANCELLED")
POSTCODE_CACHE_SECONDS = 60 * 60 * 24

# Chat category key -> code of the issue type it reports. Departments, names and
# availability come from the issue types configured in the database.
CHAT_ISSUE_CODES: dict[str, str] = {
    "pothole": "POTHOLE",
    "sign": "DAMAGED_SIGN",
    "drain": "BLOCKED_DRAIN",
    "flytip": "FLY_TIPPING",
    "graffiti": "GRAFFITI",
    "light": "STREETLIGHT",
    "parks": "PARKS_TREES",
    "other": "OTHER",
}

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
CONTACT_CODES = {
    "Email": "EMAIL",
    "Text message": "TELEPHONE",
    "Phone call": "TELEPHONE",
}


@dataclass(frozen=True)
class ChatReport:
    """A validated report from the chat."""

    category: str
    sub_issue: str
    description: str
    category_source: str
    chat_language: str
    priority: str
    reporter_urgency: str
    priority_reasons: list[str]
    postcode: str
    location_description: str
    duplicate_of: str
    possible_duplicate_of: str
    photo: str
    wants_updates: bool
    name: str
    email: str
    phone: str
    preferred_contact: str
    preferred_language: str


def _text(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if isinstance(value, str | int | float) else ""


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
    if not isinstance(case, dict) or not isinstance(reporter, dict):
        raise ValidationError("The report could not be read.")

    category = _text(case.get("category"), 20)
    if _offered_issue_type(category) is None:
        category = "other"
    priority = _text(case.get("priority_suggested"), 10)
    if priority not in PRIORITY_CODES:
        priority = "Medium"
    reporter_urgency = _text(case.get("reporter_urgency"), 10)
    reasons = case.get("priority_reasons")
    postcode = _text(location.get("postcode"), 10).upper()
    location_description = _text(location.get("description"), 200)
    if not postcode and not location_description:
        raise ValidationError("A postcode or a description of the location is needed.")
    wants_updates = reporter.get("wants_updates") is True
    photo = case.get("photo")

    return ChatReport(
        category=category,
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
        duplicate_of=_text(case.get("duplicate_of"), 20),
        possible_duplicate_of=_text(case.get("possible_duplicate_of"), 20),
        photo=photo if isinstance(photo, str) else "",
        wants_updates=wants_updates,
        name=_text(reporter.get("name"), 150) if wants_updates else "",
        email=_text(reporter.get("email"), 254) if wants_updates else "",
        phone=_text(reporter.get("phone"), 40) if wants_updates else "",
        preferred_contact=_text(reporter.get("preferred_contact"), 20),
        preferred_language=_text(reporter.get("preferred_language"), 40),
    )


def reference_for(work_item: WorkItem) -> str:
    """Return the reference shown to the public for a work item."""
    return f"{REFERENCE_PREFIX}{work_item.pk:05d}"


def work_item_for_reference(reference: str) -> WorkItem | None:
    """Return the work item a public reference points to, if any."""
    number = reference.strip().upper().removeprefix(REFERENCE_PREFIX)
    if not number.isdigit():
        return None
    return WorkItem.objects.filter(pk=int(number)).first()


def _offered_issue_type(category: str) -> IssueType | None:
    """Find the routable issue type behind a chat category, if it is offered."""
    code = CHAT_ISSUE_CODES.get(category)
    if code is None:
        return None
    return IssueType.objects.filter(
        code=code,
        kind=IssueType.Kind.ISSUE,
        department__isnull=False,
        active=True,
    ).first()


def _issue_type(category: str) -> IssueType:
    issue_type = _offered_issue_type(category)
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
        cache_key, (str(coordinates[0]), str(coordinates[1])), POSTCODE_CACHE_SECONDS
    )
    return coordinates


def nearby_open_work(category: str, postcode: str) -> WorkItem | None:
    """Return the closest open work item that may be the same problem.

    Matches the same issue type within ``DUPLICATE_RADIUS_KM`` of the
    postcode, reported in the last ``DUPLICATE_WINDOW_DAYS``. Work items
    pinned at the depot (location unknown) are never matched, because their
    pin is not where the problem is.
    """
    if category not in CHAT_ISSUE_CODES:
        return None
    coordinates = locate(postcode)
    if coordinates is None:
        return None
    lat, lng = float(coordinates[0]), float(coordinates[1])
    depot = settings.FIELD_DEPOT
    margin = Decimal("0.005")  # about 500 m: cheap pre-filter before exact distance
    candidates = (
        WorkItem.objects.filter(
            issue_type__code=CHAT_ISSUE_CODES[category],
            created_at__gte=timezone.now() - timedelta(days=DUPLICATE_WINDOW_DAYS),
            latitude__range=(coordinates[0] - margin, coordinates[0] + margin),
            longitude__range=(coordinates[1] - margin, coordinates[1] + margin),
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
        if distance <= DUPLICATE_RADIUS_KM and (best is None or distance < best[0]):
            best = (distance, item)
    return best[1] if best else None


def _decode_photo(data_url: str) -> tuple[bytes, str] | None:
    match = re.match(r"^data:image/(jpeg|png|webp);base64,(.+)$", data_url, re.S)
    if not match:
        return None
    try:
        content = base64.b64decode(match.group(2), validate=True)
    except binascii.Error, ValueError:
        return None
    if len(content) > MAX_PHOTO_BYTES:
        raise ValidationError("The photo is too large.")
    return content, "jpg" if match.group(1) == "jpeg" else match.group(1)


def _store_photo(work_item_id: int, content: bytes, extension: str) -> str:
    """Save a reporter's photo and return its URL (Cloudinary when set up)."""
    if settings.OFFICER_PHOTOS_ON_CLOUDINARY:
        try:
            result = cloudinary.uploader.upload(
                content,
                folder=f"streetfix/report-photos/{work_item_id}",
                resource_type="image",
            )
        except cloudinary.exceptions.Error as error:
            raise ValidationError("The photo could not be uploaded.") from error
        return str(result["secure_url"])
    name = default_storage.save(
        f"report-photos/{work_item_id}/{uuid.uuid4().hex}.{extension}",
        ContentFile(content),
    )
    return default_storage.url(name)


def _submission_text(
    report: ChatReport, issue_name: str, approximate_location: bool
) -> str:
    """Write the submission so a triage officer has everything in one place."""
    lines = [report.sub_issue or issue_name]
    if report.description:
        lines.append(f"Reporter's words: {report.description}")
    where = ", ".join(p for p in (report.postcode, report.location_description) if p)
    lines.append(f"Location: {where}")
    if approximate_location:
        lines.append(
            "Map pin is approximate: confirm the location from the description."
        )
    lines.append(
        f"Suggested priority: {report.priority} (rules-based, needs confirming)"
    )
    lines.extend(f"- {reason}" for reason in report.priority_reasons)
    if report.category_source:
        lines.append(f"Category: {report.category_source}")
    if report.possible_duplicate_of:
        lines.append(
            f"Possible duplicate of {report.possible_duplicate_of}: please check."
        )
    if report.chat_language and report.chat_language != "English":
        lines.append(f"Reported through the {report.chat_language} chat.")
    if report.preferred_language:
        lines.append(f"Preferred language for updates: {report.preferred_language}")
    return "\n".join(lines)


@transaction.atomic
def submit_report(report: ChatReport) -> tuple[WorkItem, ReportSubmission]:
    """Create (or join) a work item and record the public submission.

    A report the reporter confirmed as a duplicate joins the existing open
    work item, so one job collects every report about the same problem.
    """
    work_item = (
        work_item_for_reference(report.duplicate_of) if report.duplicate_of else None
    )
    if work_item is not None and work_item.status.code in FINISHED_STATUSES:
        work_item = None

    approximate = False
    if work_item is None:
        coordinates = locate(report.postcode) if report.postcode else None
        if coordinates is None:
            approximate = True
            depot = settings.FIELD_DEPOT
            coordinates = (
                Decimal(str(depot["lat"])).quantize(Decimal("0.000001")),
                Decimal(str(depot["lng"])).quantize(Decimal("0.000001")),
            )
        urgency = URGENCY_CODES[report.reporter_urgency or report.priority]
        work_item = WorkItem.objects.create(
            issue_type=_issue_type(report.category),
            latitude=coordinates[0],
            longitude=coordinates[1],
            priority=Priority.objects.get(code=PRIORITY_CODES[report.priority]),
            urgency=Urgency.objects.get(code=urgency),
            status=WorkItemStatus.objects.get(code="SUBMITTED"),
        )

    reporter = None
    if report.wants_updates and (report.email or report.phone):
        reporter = Reporter.objects.create(
            name=report.name, email=report.email, telephone=report.phone
        )
    submission = ReportSubmission.objects.create(
        work_item=work_item,
        reporter=reporter,
        contact_method=ContactMethod.objects.get(
            code=CONTACT_CODES.get(report.preferred_contact, "EMAIL")
        ),
        updates_requested=report.wants_updates,
        description=_submission_text(report, work_item.issue_type.name, approximate),
        triage_state=ReportSubmission.TriageState.LEGACY_LINKED,
    )

    photo = _decode_photo(report.photo) if report.photo else None
    if photo is not None:
        # A photo that can't be stored (for example on a read-only host
        # without Cloudinary) must never lose the report itself.
        try:
            image_url = _store_photo(work_item.pk, *photo)
        except OSError, ValidationError:
            logger.exception("Could not store the photo for work item %s", work_item.pk)
            submission.description += (
                "\nThe reporter added a photo, but it could not be saved."
            )
            submission.save(update_fields=("description",))
        else:
            ReportSubmissionPhoto.objects.create(
                report_submission=submission, image_url=image_url
            )
    return work_item, submission
