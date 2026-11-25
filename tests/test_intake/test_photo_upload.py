"""Tests for the browser's signed photo-upload endpoints."""

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import patch

import cloudinary.exceptions
import cloudinary.utils
import pytest
from django.test import Client, override_settings
from django.urls import reverse
from pytest_django.fixtures import DjangoCaptureOnCommitCallbacks

from intake.models import ReportPhotoDraft, ReportPhotoSlot, ReportSubmission
from intake.services.photos import VerifiedPhoto
from intake.services.rate_limit import PHOTO_AUTHORIZATION

pytestmark = pytest.mark.django_db

CONFIG = SimpleNamespace(cloud_name="demo", api_key="key", api_secret="secret")  # noqa: S106


@pytest.fixture(autouse=True)
def photo_provider() -> Iterator[None]:
    """Enable public reporting and a configured provider without network calls."""
    with (
        override_settings(
            INTAKE_PUBLIC_REPORTING_ENABLED=True,
            INTAKE_PHOTO_UPLOAD_PRESET="report-photos",
        ),
        patch("intake.services.photo_upload.cloudinary.config", return_value=CONFIG),
        patch("intake.services.photo_upload.verify_upload_preset"),
    ):
        yield


def authorize(client: Client, draft: str | None = None) -> dict[str, object]:
    """Ask for an upload authorization and return the JSON body."""
    response = client.post(
        reverse("intake:photo_authorize"),
        {"draft": draft},
        content_type="application/json",
    )
    return {"status": response.status_code, **response.json()}


def verified(slot_id: str) -> VerifiedPhoto:
    """Provider metadata for a successfully uploaded photo."""
    return VerifiedPhoto(
        public_id=ReportPhotoSlot.objects.get(pk=slot_id).public_id,
        asset_id=f"asset-{slot_id}",
        format="jpg",
        size_bytes=1000,
        version=1,
    )


def verify(client: Client, grant: dict[str, object]) -> int:
    """Verify a reserved slot as if the provider had received the upload."""
    with patch(
        "intake.services.photo_reservations.fetch_verified_photo",
        return_value=verified(str(grant["slot"])),
    ):
        return client.post(
            reverse(
                "intake:photo_verify",
                args=[grant["draft"], grant["slot"]],
            )
        ).status_code


def test_authorization_reserves_a_slot_and_signs_exactly_that_asset(
    client: Client,
) -> None:
    """The browser can only upload to the server-reserved public ID."""
    grant = authorize(client)

    assert grant["status"] == 201
    slot = ReportPhotoSlot.objects.get(pk=str(grant["slot"]))
    fields = grant["fields"]
    assert isinstance(fields, dict)
    assert fields["public_id"] == slot.public_id
    assert fields["upload_preset"] == "report-photos"
    signed = {k: fields[k] for k in ("public_id", "timestamp", "upload_preset")}
    assert fields["signature"] == cloudinary.utils.api_sign_request(signed, "secret")
    assert grant["upload_url"] == "https://api.cloudinary.com/v1_1/demo/image/upload"
    assert "secret" not in str(grant)


def test_photos_are_unavailable_until_a_preset_is_configured(client: Client) -> None:
    """Nothing is reserved when the deployment has not set photos up."""
    with override_settings(INTAKE_PHOTO_UPLOAD_PRESET=""):
        grant = authorize(client)
    assert grant["status"] == 400
    assert not ReportPhotoDraft.objects.exists()


@override_settings(INTAKE_PUBLIC_REPORTING_ENABLED=False)
def test_photo_endpoints_respect_the_reporting_gate(client: Client) -> None:
    """Closing public reporting also closes uploads."""
    response = client.post(reverse("intake:photo_authorize"))
    assert response.status_code == 404
    assert not ReportPhotoDraft.objects.exists()


def test_at_most_three_photos_per_draft(client: Client) -> None:
    """A fourth reservation in one draft is refused."""
    draft = str(authorize(client)["draft"])
    for _ in range(2):
        assert authorize(client, draft)["status"] == 201
    assert authorize(client, draft)["status"] == 400
    assert ReportPhotoSlot.objects.count() == 3


def test_authorizations_are_rate_limited_per_address(client: Client) -> None:
    """Too many authorizations from one address return 429."""
    for _ in range(PHOTO_AUTHORIZATION.limit):
        assert authorize(client)["status"] == 201
    assert authorize(client)["status"] == 429


def test_another_browser_cannot_use_a_draft_or_verify_its_slots(
    client: Client,
) -> None:
    """Drafts and slots are bound to the browser session that created them."""
    grant = authorize(client)
    stranger = Client()

    assert authorize(stranger, str(grant["draft"]))["status"] == 400
    assert verify(stranger, grant) == 400


def test_verification_reports_unfinished_uploads(client: Client) -> None:
    """A slot is not marked verified until the provider has the photo."""
    grant = authorize(client)
    with patch(
        "intake.services.photo_reservations.fetch_verified_photo",
        side_effect=cloudinary.exceptions.NotFound("missing"),
    ):
        response = client.post(
            reverse("intake:photo_verify", args=[grant["draft"], grant["slot"]])
        )
    assert response.status_code == 404
    assert ReportPhotoSlot.objects.get().asset_id is None


def test_report_with_verified_photos_attaches_them_atomically(
    client: Client,
    django_capture_on_commit_callbacks: DjangoCaptureOnCommitCallbacks,
) -> None:
    """A submitted report owns exactly the photos reserved in its draft."""
    first = authorize(client)
    second = authorize(client, str(first["draft"]))
    assert verify(client, first) == 200
    assert verify(client, second) == 200

    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(
            reverse("intake:submit_report"),
            {
                "other_selected": "on",
                "description": "An issue.",
                "photo_draft": first["draft"],
                "photo_slots": f"{first['slot']},{second['slot']}",
            },
        )

    assert response.status_code == 302
    submission = ReportSubmission.objects.get()
    assert submission.photo_draft.slots.count() == 2


def test_report_with_unverified_photo_is_not_saved(client: Client) -> None:
    """Photos that did not finish uploading never produce a half-attached report."""
    grant = authorize(client)

    response = client.post(
        reverse("intake:submit_report"),
        {
            "other_selected": "on",
            "description": "An issue.",
            "photo_draft": grant["draft"],
            "photo_slots": str(grant["slot"]),
        },
    )

    assert response.status_code == 200
    assert b"finish uploading" in response.content
    assert not ReportSubmission.objects.exists()


def test_report_cannot_claim_another_browsers_photos(client: Client) -> None:
    """Knowing a draft ID is not enough to attach its photos."""
    grant = authorize(client)
    assert verify(client, grant) == 200

    response = Client().post(
        reverse("intake:submit_report"),
        {
            "other_selected": "on",
            "description": "An issue.",
            "photo_draft": grant["draft"],
            "photo_slots": str(grant["slot"]),
        },
    )

    assert response.status_code == 200
    assert not ReportSubmission.objects.exists()
    assert ReportPhotoDraft.objects.get().submission is None


def test_form_offers_photos_only_when_configured(client: Client) -> None:
    """The form shows the upload control only for a configured deployment."""
    url = reverse("intake:submit_report")
    assert b"data-photo-upload" in client.get(url).content
    with override_settings(INTAKE_PHOTO_UPLOAD_PRESET=""):
        content = client.get(url).content
    assert b"data-photo-upload" not in content
    assert b"Photo uploads are not available." in content
