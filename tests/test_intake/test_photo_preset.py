"""Tests for Cloudinary report-photo preset checks."""

from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from intake.services.photos import verify_upload_preset


def test_signed_authenticated_preset_is_accepted() -> None:
    """The named preset is checked against the provider, not the browser."""
    preset = {
        "name": "report-photos",
        "unsigned": False,
        "settings": {"type": "authenticated"},
    }
    with patch(
        "intake.services.photos.cloudinary.api.upload_preset",
        return_value=preset,
    ) as lookup:
        verify_upload_preset("report-photos")
    lookup.assert_called_once_with("report-photos")


@pytest.mark.parametrize(
    "preset",
    [
        {
            "name": "report-photos",
            "unsigned": True,
            "settings": {"type": "authenticated"},
        },
        {"name": "another", "unsigned": False, "settings": {"type": "authenticated"}},
        {"name": "report-photos", "settings": {"type": "authenticated"}},
        {"name": "report-photos", "unsigned": False, "settings": None},
        {"name": "report-photos", "unsigned": False, "settings": {}},
        {"name": "report-photos", "unsigned": False, "settings": {"type": "upload"}},
        {
            "name": "report-photos",
            "unsigned": False,
            "settings": {"type": "authenticated", "disallow_public_id": True},
        },
        {
            "name": "report-photos",
            "unsigned": False,
            "disallow_public_id": True,
            "settings": {"type": "authenticated"},
        },
        {
            "name": "report-photos",
            "unsigned": False,
            "settings": {"type": "authenticated", "overwrite": True},
        },
        {
            "name": "report-photos",
            "unsigned": False,
            "settings": {"type": "authenticated", "overwrite": "true"},
        },
    ],
)
def test_unsafe_preset_is_rejected(preset: dict[str, object]) -> None:
    """Missing or unsafe security settings fail closed."""
    with (
        patch(
            "intake.services.photos.cloudinary.api.upload_preset",
            return_value=preset,
        ),
        pytest.raises(ValidationError),
    ):
        verify_upload_preset("report-photos")
