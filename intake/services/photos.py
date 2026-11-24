"""Verify Cloudinary metadata for report photos."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import cloudinary.api
from django.core.exceptions import ValidationError

MAX_REPORT_PHOTOS = 3
MAX_PHOTO_BYTES = 10_000_000
ALLOWED_FORMATS = frozenset({"jpg", "jpeg", "png", "webp", "heic"})


@dataclass(frozen=True)
class VerifiedPhoto:
    """Provider-verified identity and properties of an uploaded photo."""

    public_id: str
    asset_id: str
    format: str
    size_bytes: int
    version: int


def verify_upload_preset(name: str) -> None:
    """Require a signed preset with authenticated delivery in provider settings."""
    if not name:
        raise ValidationError("A report-photo upload preset is required.")
    preset = cloudinary.api.upload_preset(name)
    if (
        preset.get("name") != name
        or preset.get("unsigned") is not False
        or not isinstance(preset.get("settings"), Mapping)
    ):
        raise ValidationError("The report-photo upload preset is not signed.")
    settings: Mapping[str, Any] = preset["settings"]
    if settings.get("type") != "authenticated":
        raise ValidationError(
            "The report-photo upload preset must use authenticated delivery."
        )
    if (
        preset.get("disallow_public_id") is True
        or settings.get("disallow_public_id") is True
    ):
        raise ValidationError("The report-photo preset must allow reserved asset IDs.")
    overwrite = settings.get("overwrite")
    if overwrite is not None and overwrite is not False:
        raise ValidationError("The report-photo preset must not allow overwrites.")


def fetch_verified_photo(expected_public_id: str) -> VerifiedPhoto:
    """Fetch and verify an authenticated asset using a server-reserved ID."""
    if not expected_public_id:
        raise ValidationError("A reserved asset identifier is required.")
    metadata = cloudinary.api.resource(
        expected_public_id, resource_type="image", type="authenticated"
    )
    return verify_photo_metadata(metadata, expected_public_id=expected_public_id)


def verify_photo_metadata(
    metadata: Mapping[str, Any], *, expected_public_id: str
) -> VerifiedPhoto:
    """Validate metadata fetched by the server, not a browser callback."""
    public_id = metadata.get("public_id")
    asset_id = metadata.get("asset_id")
    format_name = metadata.get("format")
    size = metadata.get("bytes")
    version = metadata.get("version")
    if not expected_public_id or public_id != expected_public_id:
        raise ValidationError("The uploaded photo does not match the reserved asset.")
    if (
        metadata.get("resource_type") != "image"
        or metadata.get("type") != "authenticated"
    ):
        raise ValidationError(
            "The uploaded photo must use authenticated image delivery."
        )
    if not isinstance(asset_id, str) or not asset_id.strip():
        raise ValidationError("The uploaded photo has no verified asset identity.")
    if not isinstance(format_name, str) or format_name.lower() not in ALLOWED_FORMATS:
        raise ValidationError("The uploaded photo has an unsupported format.")
    if type(size) is not int or not 0 < size <= MAX_PHOTO_BYTES:
        raise ValidationError("The uploaded photo must be no larger than 10 MB.")
    if type(version) is not int or version <= 0:
        raise ValidationError("The uploaded photo has no verified version.")
    return VerifiedPhoto(
        public_id=expected_public_id,
        asset_id=asset_id,
        format=format_name.lower(),
        size_bytes=size,
        version=version,
    )
