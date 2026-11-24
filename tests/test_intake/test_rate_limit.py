"""Tests for rolling per-address limits on public actions."""

from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.test import RequestFactory
from django.utils import timezone
from pytest_django.fixtures import Settings

from intake.models import RateLimitRecord
from intake.services.rate_limit import (
    PHOTO_AUTHORIZATION,
    REPORT_SUBMISSION,
    client_address,
    reserve,
)

pytestmark = pytest.mark.django_db


def test_limit_is_rolling_and_per_address() -> None:
    """The limit applies independently for each address and rolls forward."""
    now = timezone.now()
    with patch("intake.services.rate_limit.timezone.now", return_value=now):
        for _ in range(PHOTO_AUTHORIZATION.limit):
            reserve(PHOTO_AUTHORIZATION, "192.0.2.1")
        with pytest.raises(ValidationError, match="Too many"):
            reserve(PHOTO_AUTHORIZATION, "192.0.2.1")
        reserve(PHOTO_AUTHORIZATION, "192.0.2.2")
    with patch(
        "intake.services.rate_limit.timezone.now",
        return_value=now + PHOTO_AUTHORIZATION.window,
    ):
        reserve(PHOTO_AUTHORIZATION, "192.0.2.1")
    assert RateLimitRecord.objects.count() == 2
    assert all(
        "192.0.2" not in rate.address_digest for rate in RateLimitRecord.objects.all()
    )


def test_actions_are_limited_separately() -> None:
    """Using up one action does not block another from the same address."""
    for _ in range(REPORT_SUBMISSION.limit):
        reserve(REPORT_SUBMISSION, "192.0.2.1")
    with pytest.raises(ValidationError, match="Too many"):
        reserve(REPORT_SUBMISSION, "192.0.2.1")
    reserve(PHOTO_AUTHORIZATION, "192.0.2.1")


def test_mapped_ipv6_uses_same_rate_limit_as_ipv4() -> None:
    """Equivalent address representations cannot evade the limit."""
    for _ in range(REPORT_SUBMISSION.limit):
        reserve(REPORT_SUBMISSION, "192.0.2.1")
    with pytest.raises(ValidationError, match="Too many"):
        reserve(REPORT_SUBMISSION, "::ffff:192.0.2.1")


def test_invalid_addresses_and_corrupt_state_fail_closed() -> None:
    """Missing IPs and invalid persisted state do not allow the action."""
    for address in ("", "not-an-address", "fe80::1%interface"):
        with pytest.raises(ValidationError, match="valid client IP"):
            reserve(REPORT_SUBMISSION, address)
    reserve(REPORT_SUBMISSION, "192.0.2.1")
    RateLimitRecord.objects.update(timestamps=["bad"])
    with pytest.raises(ValidationError, match="unavailable"):
        reserve(REPORT_SUBMISSION, "192.0.2.1")


def test_client_address_comes_only_from_the_configured_header(
    settings: Settings,
) -> None:
    """A client-supplied forwarding header is ignored unless configured."""
    request = RequestFactory().get(
        "/",
        REMOTE_ADDR="192.0.2.1",
        HTTP_X_FORWARDED_FOR="198.51.100.9",
    )
    assert client_address(request) == "192.0.2.1"
    settings.INTAKE_CLIENT_IP_HEADER = "HTTP_X_FORWARDED_FOR"
    assert client_address(request) == "198.51.100.9"


def test_cleanup_keeps_active_rate_limits() -> None:
    """Expired address records are removed without resetting active limits."""
    now = timezone.now()
    with patch(
        "intake.services.rate_limit.timezone.now",
        return_value=now - timedelta(hours=3),
    ):
        reserve(REPORT_SUBMISSION, "192.0.2.1")
    reserve(REPORT_SUBMISSION, "192.0.2.2")
    call_command("prune_rate_limits")
    assert RateLimitRecord.objects.count() == 1
    assert RateLimitRecord.objects.get().last_hit_at > now - timedelta(hours=1)
