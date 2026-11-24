"""Authorize signed browser uploads of report photos to Cloudinary."""

import time
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID

import cloudinary
import cloudinary.utils
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils import timezone

from intake.models import ReportPhotoDraft, ReportPhotoSlot
from intake.services.photo_reservations import create_photo_draft, reserve_photo_slot
from intake.services.photos import verify_upload_preset
from intake.services.rate_limit import PHOTO_AUTHORIZATION, reserve

DRAFT_LIFETIME = timedelta(hours=2)
PRESET_CHECK_SECONDS = 300
PRESET_CACHE_KEY = "intake:photo-preset-verified"


@dataclass(frozen=True)
class UploadAuthorization:
    """What the browser needs to upload one reserved photo."""

    draft_id: UUID
    slot_id: UUID
    upload_url: str
    fields: dict[str, str | int]


def photo_upload_enabled() -> bool:
    """Offer photos only when a preset and provider credentials are configured."""
    config = cloudinary.config()
    return bool(
        settings.INTAKE_PHOTO_UPLOAD_PRESET
        and config.cloud_name
        and config.api_key
        and config.api_secret
    )


def _require_verified_preset() -> None:
    if cache.get(PRESET_CACHE_KEY):
        return
    verify_upload_preset(settings.INTAKE_PHOTO_UPLOAD_PRESET)
    cache.set(PRESET_CACHE_KEY, True, PRESET_CHECK_SECONDS)


def authorize_upload(
    *, session_key: str, address: str, draft_id: UUID | None
) -> UploadAuthorization:
    """Reserve a photo slot and sign an upload for exactly that asset ID."""
    if not photo_upload_enabled():
        raise ValidationError("Photo uploads are not available.")
    reserve(PHOTO_AUTHORIZATION, address)
    _require_verified_preset()
    if draft_id is None:
        draft: ReportPhotoDraft = create_photo_draft(
            session_key=session_key, expires_at=timezone.now() + DRAFT_LIFETIME
        )
        draft_id = draft.pk
    slot: ReportPhotoSlot = reserve_photo_slot(
        draft_id=draft_id, session_key=session_key
    )
    config = cloudinary.config()
    fields: dict[str, str | int] = {
        "public_id": slot.public_id,
        "timestamp": int(time.time()),
        "upload_preset": settings.INTAKE_PHOTO_UPLOAD_PRESET,
    }
    fields["signature"] = cloudinary.utils.api_sign_request(
        dict(fields), config.api_secret
    )
    fields["api_key"] = config.api_key
    return UploadAuthorization(
        draft_id=draft_id,
        slot_id=slot.pk,
        upload_url=f"https://api.cloudinary.com/v1_1/{config.cloud_name}/image/upload",
        fields=fields,
    )
