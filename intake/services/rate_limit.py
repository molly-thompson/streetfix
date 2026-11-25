"""Enforce rolling, per-address limits on public actions."""

from dataclasses import dataclass
from datetime import timedelta
from ipaddress import IPv6Address, ip_address

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import HttpRequest
from django.utils import timezone
from django.utils.crypto import salted_hmac

from intake.models import RateLimitRecord


@dataclass(frozen=True)
class RateLimit:
    """How many times an address may perform a public action in a window."""

    scope: str
    limit: int
    window: timedelta


PHOTO_AUTHORIZATION = RateLimit("photo_authorization", 20, timedelta(hours=1))
REPORT_SUBMISSION = RateLimit("report_submission", 10, timedelta(hours=1))
REFERENCE_LOOKUP = RateLimit("reference_lookup", 20, timedelta(hours=1))
ISSUE_TEXT_SEARCH = RateLimit("issue_text_search", 60, timedelta(hours=1))
RATE_LIMITED = "rate_limited"
LONGEST_WINDOW = max(
    PHOTO_AUTHORIZATION.window,
    REPORT_SUBMISSION.window,
    REFERENCE_LOOKUP.window,
    ISSUE_TEXT_SEARCH.window,
)


def client_address(request: HttpRequest) -> str:
    """Return the client address from the deployment's trusted header.

    The header is configured with INTAKE_CLIENT_IP_HEADER, as a WSGI META key.
    Only name a header that the hosting edge sets itself and clients cannot
    forge. A missing or invalid value makes the limited action unavailable.
    """
    return str(request.META.get(settings.INTAKE_CLIENT_IP_HEADER, "")).strip()


@transaction.atomic
def reserve(rule: RateLimit, address: str) -> None:
    """Count one use of an action for a client address, or fail closed."""
    try:
        parsed = ip_address(address)
    except ValueError as exc:
        raise ValidationError("A valid client IP address is required.") from exc
    if isinstance(parsed, IPv6Address):
        if parsed.scope_id is not None:
            raise ValidationError("A valid client IP address is required.")
        if parsed.ipv4_mapped is not None:
            parsed = parsed.ipv4_mapped
    digest = salted_hmac(
        f"intake.rate_limit.{rule.scope}", str(parsed), algorithm="sha256"
    ).hexdigest()
    RateLimitRecord.objects.get_or_create(
        scope=rule.scope,
        address_digest=digest,
        defaults={"last_hit_at": timezone.now()},
    )
    record = RateLimitRecord.objects.select_for_update().get(
        scope=rule.scope, address_digest=digest
    )
    now = timezone.now()
    timestamps = record.timestamps
    if not isinstance(timestamps, list) or any(
        type(value) is not int for value in timestamps
    ):
        raise ValidationError("This action is temporarily unavailable.")
    cutoff = int((now - rule.window).timestamp() * 1_000_000)
    recent = [value for value in timestamps if value > cutoff]
    if len(recent) >= rule.limit:
        raise ValidationError("Too many requests. Try again later.", code=RATE_LIMITED)
    recent.append(int(now.timestamp() * 1_000_000))
    record.timestamps = recent
    record.last_hit_at = now
    record.save(update_fields=("timestamps", "last_hit_at"))
