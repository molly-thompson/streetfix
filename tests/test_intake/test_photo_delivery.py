"""Tests for authenticated staff access to report photos."""

from collections.abc import Callable
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.http import StreamingHttpResponse
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from employees.organisation_models import Employee
from employees.work_models import WorkAssignment, WorkItem
from intake.models import ReportPhotoDraft, ReportPhotoSlot, ReportSubmission
from intake.services.photo_delivery import (
    PhotoStream,
    PhotoUnavailableError,
    open_report_photo,
)
from intake.services.photo_reservations import create_photo_draft, reserve_photo_slot
from intake.services.photos import VerifiedPhoto

pytestmark = pytest.mark.django_db


class ProviderResponse(BytesIO):
    """Provide an in-memory upstream response with HTTP-like headers."""

    def __init__(self, content: bytes) -> None:
        """Set a body and corresponding content length."""
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content))}


def test_photo_proxy_checks_permissions_and_streams_without_redirect(
    client: Client, make_employee: Callable[..., Employee]
) -> None:
    """Only employee reviewers receive bytes, never the signed provider URL."""
    submission = ReportSubmission.objects.create(
        description="A", updates_requested=False
    )
    draft = create_photo_draft(
        session_key="session", expires_at=timezone.now() + timedelta(hours=2)
    )
    draft.submission = submission
    draft.save(update_fields=("submission",))
    slot = reserve_photo_slot_for_test(draft)
    url = reverse("intake:report_photo", args=[slot.pk])
    assert client.get(url).status_code == 302
    reviewer = make_employee()
    client.force_login(reviewer.user)
    assert client.get(url).status_code == 404
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(reviewer.user)
    provider = ProviderResponse(b"data")
    verified = VerifiedPhoto(slot.public_id, "asset", "png", 4, 42)
    with (
        patch(
            "intake.services.photo_delivery.fetch_verified_photo", return_value=verified
        ),
        patch(
            "intake.services.photo_delivery.cloudinary.utils.cloudinary_url",
            return_value=("https://res.cloudinary.com/test/signed", {}),
        ),
        patch("intake.services.photo_delivery.build_opener") as opener,
    ):
        opener.return_value.open.return_value = provider
        response = client.get(url)
        assert response.status_code == 200
        assert isinstance(response, StreamingHttpResponse)
        assert b"".join(response.streaming_content) == b"data"
        assert "no-store" in response.headers["Cache-Control"]
        assert "cloudinary" not in str(response.headers).lower()
        response.close()
        assert provider.closed
    non_employee = get_user_model().objects.create_user(
        username="nonemployee", email="nonemployee@example.com"
    )
    non_employee.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(non_employee)
    assert client.get(url).status_code == 403


def reserve_photo_slot_for_test(draft: ReportPhotoDraft) -> ReportPhotoSlot:
    """Create an attached, previously verified slot."""
    return ReportPhotoSlot.objects.create(
        draft=draft, asset_id="asset", format="png", size_bytes=4, version=42
    )


def test_changed_provider_version_is_not_delivered() -> None:
    """A replaced provider asset is rejected rather than shown to staff."""
    draft = create_photo_draft(
        session_key="session", expires_at=timezone.now() + timedelta(hours=2)
    )
    slot = reserve_photo_slot(draft_id=draft.pk, session_key="session")
    slot.asset_id = "asset"
    slot.format = "png"
    slot.size_bytes = 4
    slot.version = 42
    slot.save()
    with patch(
        "intake.services.photo_delivery.fetch_verified_photo",
        return_value=VerifiedPhoto(slot.public_id, "asset", "png", 4, 43),
    ):
        with pytest.raises(PhotoUnavailableError):
            open_report_photo(slot)


def test_provider_redirect_to_another_host_is_not_opened() -> None:
    """Signed delivery is confined to the expected HTTPS provider host."""
    draft = create_photo_draft(
        session_key="session", expires_at=timezone.now() + timedelta(hours=2)
    )
    slot = reserve_photo_slot(draft_id=draft.pk, session_key="session")
    slot.asset_id = "asset"
    slot.format = "png"
    slot.size_bytes = 4
    slot.version = 42
    with (
        patch(
            "intake.services.photo_delivery.fetch_verified_photo",
            return_value=VerifiedPhoto(slot.public_id, "asset", "png", 4, 42),
        ),
        patch(
            "intake.services.photo_delivery.cloudinary.utils.cloudinary_url",
            return_value=("https://another.example/signed", {}),
        ),
        patch("intake.services.photo_delivery.build_opener") as opener,
        pytest.raises(PhotoUnavailableError),
    ):
        open_report_photo(slot)
    opener.assert_not_called()


def test_current_assignees_can_view_photos_but_lose_access_when_released(
    client: Client,
    make_employee: Callable[..., Employee],
    make_work_item: Callable[..., WorkItem],
) -> None:
    """Access follows the currently linked work and open assignment."""
    employee = make_employee()
    work = make_work_item()
    submission = ReportSubmission.objects.create(
        description="A",
        updates_requested=False,
        work_item=work,
        triage_state="ACCEPTED",
    )
    draft = create_photo_draft(
        session_key="session", expires_at=timezone.now() + timedelta(hours=2)
    )
    draft.submission = submission
    draft.save(update_fields=("submission",))
    slot = reserve_photo_slot_for_test(draft)
    url = reverse("intake:report_photo", args=[slot.pk])
    client.force_login(employee.user)
    assert client.get(url).status_code == 404
    assignment = WorkAssignment.assign(work, employee)
    with patch(
        "intake.views.open_report_photo",
        side_effect=lambda _: PhotoStream(BytesIO(b"data"), 4),
    ):
        response = client.get(url)
        assert response.status_code == 200
        assert isinstance(response, StreamingHttpResponse)
        assert b"".join(response.streaming_content) == b"data"
        response.close()
        job = client.get(reverse("employees:my_job", args=[work.pk]))
        assert url.encode() in job.content
        assert "no-store" in job.headers["Cache-Control"]
        submission.work_item = None
        submission.save(update_fields=("work_item",))
        assert client.get(url).status_code == 404
        submission.work_item = work
        submission.save(update_fields=("work_item",))
        assignment.release(reason="Reassigned")
        assert client.get(url).status_code == 404
