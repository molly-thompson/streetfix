"""Reserve report photo identifiers against a server-side browser session."""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from intake.models import ReportPhotoDraft, ReportPhotoSlot, ReportSubmission
from intake.services.photos import MAX_REPORT_PHOTOS, fetch_verified_photo


def _session_digest(session_key: str) -> str:
    if not session_key:
        raise ValidationError("A browser session is required for photo uploads.")
    return salted_hmac(
        "intake.report_photo_session", session_key, algorithm="sha256"
    ).hexdigest()


def create_photo_draft(*, session_key: str, expires_at: datetime) -> ReportPhotoDraft:
    """Create an upload draft with a server-selected expiry."""
    digest = _session_digest(session_key)
    if timezone.is_naive(expires_at) or expires_at <= timezone.now():
        raise ValidationError("The photo draft expiry must be in the future.")
    return ReportPhotoDraft.objects.create(
        session_digest=digest,
        expires_at=expires_at,
    )


@transaction.atomic
def reserve_photo_slot(*, draft_id: UUID, session_key: str) -> ReportPhotoSlot:
    """Reserve one of at most three unpredictable IDs for the owning session."""
    digest = _session_digest(session_key)
    draft = ReportPhotoDraft.objects.select_for_update().filter(pk=draft_id).first()
    if draft is None or not constant_time_compare(digest, draft.session_digest):
        raise ValidationError("The photo upload draft is unavailable.")
    if draft.submission_id is not None or draft.expires_at <= timezone.now():
        raise ValidationError("The photo upload draft is no longer available.")
    if draft.slots.count() >= MAX_REPORT_PHOTOS:
        raise ValidationError("A report can have at most three photos.")
    return ReportPhotoSlot.objects.create(draft=draft)


def verify_photo_slot(
    *, draft_id: UUID, slot_id: UUID, session_key: str
) -> ReportPhotoSlot:
    """Fetch provider metadata and record it only for the owning open draft."""
    digest = _session_digest(session_key)
    slot = (
        ReportPhotoSlot.objects.select_related("draft")
        .filter(pk=slot_id, draft_id=draft_id)
        .first()
    )
    if (
        slot is None
        or not constant_time_compare(digest, slot.draft.session_digest)
        or slot.draft.submission_id is not None
        or slot.draft.expires_at <= timezone.now()
    ):
        raise ValidationError("The photo upload slot is unavailable.")
    verified = fetch_verified_photo(slot.public_id)
    with transaction.atomic():
        draft = ReportPhotoDraft.objects.select_for_update().get(pk=draft_id)
        slot = ReportPhotoSlot.objects.select_for_update().get(pk=slot_id, draft=draft)
        if (
            not constant_time_compare(digest, draft.session_digest)
            or draft.submission_id is not None
            or draft.expires_at <= timezone.now()
        ):
            raise ValidationError("The photo upload slot is unavailable.")
        if slot.asset_id is not None and (
            slot.asset_id != verified.asset_id
            or slot.version != verified.version
            or slot.format != verified.format
            or slot.size_bytes != verified.size_bytes
        ):
            raise ValidationError("The verified photo has changed.")
        slot.asset_id = verified.asset_id
        slot.version = verified.version
        slot.format = verified.format
        slot.size_bytes = verified.size_bytes
        slot.save(update_fields=("asset_id", "version", "format", "size_bytes"))
    return slot


@transaction.atomic
def attach_verified_draft(
    *,
    submission_id: int,
    draft_id: UUID,
    slot_ids: Sequence[UUID],
    session_key: str,
) -> None:
    """Attach all reserved, verified photos to one newly received report."""
    digest = _session_digest(session_key)
    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    if (
        submission.triage_state != ReportSubmission.TriageState.RECEIVED
        or submission.work_item_id is not None
    ):
        raise ValidationError("Photos can only be attached to a new report.")
    draft = ReportPhotoDraft.objects.select_for_update().filter(pk=draft_id).first()
    if (
        draft is None
        or not constant_time_compare(digest, draft.session_digest)
        or draft.submission_id is not None
        or draft.expires_at <= timezone.now()
    ):
        raise ValidationError("The photo upload draft is unavailable.")
    slots = list(draft.slots.select_for_update())
    submitted_ids = set(slot_ids)
    if (
        not slots
        or len(slots) > MAX_REPORT_PHOTOS
        or len(submitted_ids) != len(slot_ids)
        or submitted_ids != {slot.pk for slot in slots}
        or any(slot.asset_id is None for slot in slots)
    ):
        raise ValidationError(
            "All selected photos must finish uploading before sending the report."
        )
    draft.submission = submission
    draft.save(update_fields=("submission",))
