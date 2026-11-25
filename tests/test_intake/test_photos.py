"""Tests for server-side report photo metadata verification."""

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from intake.services.photos import (
    MAX_PHOTO_BYTES,
    fetch_verified_photo,
    verify_photo_metadata,
)


def metadata() -> dict[str, object]:
    """Return a representative provider response."""
    return {
        "public_id": "intake/random-id",
        "asset_id": "provider-asset-id",
        "resource_type": "image",
        "type": "authenticated",
        "format": "heic",
        "bytes": MAX_PHOTO_BYTES,
        "version": 123,
    }


def test_verified_authenticated_photo_at_size_limit() -> None:
    """Supported images retain only provider-verified identity and properties."""
    photo = verify_photo_metadata(metadata(), expected_public_id="intake/random-id")
    assert photo.format == "heic"
    assert photo.size_bytes == MAX_PHOTO_BYTES


def test_fetch_uses_authenticated_provider_lookup() -> None:
    """The browser cannot supply the metadata used for verification."""
    with patch(
        "intake.services.photos.cloudinary.api.resource", return_value=metadata()
    ) as lookup:
        photo = fetch_verified_photo("intake/random-id")

    lookup.assert_called_once_with(
        "intake/random-id", resource_type="image", type="authenticated"
    )
    assert photo.asset_id == "provider-asset-id"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("public_id", "intake/another-id"),
        ("asset_id", ""),
        ("resource_type", "video"),
        ("type", "upload"),
        ("type", "private"),
        ("format", "svg"),
        ("bytes", MAX_PHOTO_BYTES + 1),
        ("bytes", 0),
        ("bytes", True),
        ("bytes", "100"),
        ("version", 0),
        ("version", True),
    ],
)
def test_untrusted_or_invalid_assets_cannot_be_attached(
    field: str, value: object
) -> None:
    """Only matching authenticated images within the configured limit pass."""
    payload = metadata()
    payload[field] = value
    with pytest.raises(ValidationError):
        verify_photo_metadata(payload, expected_public_id="intake/random-id")
