"""Tests for session-bound photo upload reservations."""

from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from intake.services.photo_reservations import (
    create_photo_draft,
    reserve_photo_slot,
    verify_photo_slot,
)
from intake.services.photos import VerifiedPhoto

pytestmark = pytest.mark.django_db


def test_draft_reserves_three_distinct_server_ids_for_owning_session() -> None:
    """A draft is limited to three slots and never accepts another session."""
    draft = create_photo_draft(
        session_key="session-one", expires_at=timezone.now() + timedelta(hours=2)
    )
    with pytest.raises(ValidationError, match="unavailable"):
        reserve_photo_slot(draft_id=draft.pk, session_key="session-two")
    slots = [
        reserve_photo_slot(draft_id=draft.pk, session_key="session-one")
        for _ in range(3)
    ]
    assert len({slot.public_id for slot in slots}) == 3
    assert all(slot.public_id.startswith("intake/report-photos/") for slot in slots)
    with pytest.raises(ValidationError, match="at most three"):
        reserve_photo_slot(draft_id=draft.pk, session_key="session-one")


def test_expired_unknown_and_sessionless_drafts_are_unavailable() -> None:
    """An invalid, expired or unknown draft cannot reserve an asset."""
    with pytest.raises(ValidationError, match="session"):
        create_photo_draft(
            session_key="", expires_at=timezone.now() + timedelta(hours=2)
        )
    with pytest.raises(ValidationError, match="future"):
        create_photo_draft(session_key="session", expires_at=timezone.now())
    with pytest.raises(ValidationError, match="unavailable"):
        reserve_photo_slot(draft_id=uuid4(), session_key="session")
    draft = create_photo_draft(
        session_key="session", expires_at=timezone.now() + timedelta(hours=2)
    )
    draft.expires_at = timezone.now() - timedelta(seconds=1)
    draft.save(update_fields=("expires_at",))
    with pytest.raises(ValidationError, match="no longer available"):
        reserve_photo_slot(draft_id=draft.pk, session_key="session")


def test_slot_verification_uses_server_metadata_and_checks_ownership() -> None:
    """Only the owning session can record the provider's verified metadata."""
    draft = create_photo_draft(
        session_key="session", expires_at=timezone.now() + timedelta(hours=2)
    )
    slot = reserve_photo_slot(draft_id=draft.pk, session_key="session")
    photo = VerifiedPhoto(slot.public_id, "asset-one", "jpeg", 123, 42)
    with patch(
        "intake.services.photo_reservations.fetch_verified_photo", return_value=photo
    ) as fetch:
        with pytest.raises(ValidationError, match="unavailable"):
            verify_photo_slot(
                draft_id=draft.pk, slot_id=slot.pk, session_key="another-session"
            )
        fetch.assert_not_called()
        verified = verify_photo_slot(
            draft_id=draft.pk, slot_id=slot.pk, session_key="session"
        )
        fetch.assert_called_once_with(slot.public_id)
        assert verified.asset_id == "asset-one"
        assert verified.version == 42
        verify_photo_slot(draft_id=draft.pk, slot_id=slot.pk, session_key="session")
        fetch.return_value = VerifiedPhoto(slot.public_id, "asset-one", "jpeg", 123, 43)
        with pytest.raises(ValidationError, match="changed"):
            verify_photo_slot(draft_id=draft.pk, slot_id=slot.pk, session_key="session")


def test_database_rejects_partially_verified_photo() -> None:
    """Partial provider metadata cannot be mistaken for an attached photo."""
    draft = create_photo_draft(
        session_key="session", expires_at=timezone.now() + timedelta(hours=2)
    )
    slot = reserve_photo_slot(draft_id=draft.pk, session_key="session")
    slot.asset_id = "asset"
    with pytest.raises(IntegrityError), transaction.atomic():
        slot.save(update_fields=("asset_id",))
