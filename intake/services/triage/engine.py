"""Queue and process optional, reviewer-requested engine assessments."""

import hashlib
import json
import logging
import re
from datetime import timedelta
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from employees.organisation_models import Employee
from intake.models import ReportSubmission, TriageEngineJob, TriagePolicy
from intake.services.triage.taxonomy import snapshot_taxonomy

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 1024 * 1024
LEASE_MINUTES = 5


class EngineError(Exception):
    """A safe, operator-facing engine failure."""


def _digest(value: object) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _configuration() -> tuple[str, str, str]:
    if settings.TRIAGE_ENGINE_MODE not in ("shadow", "review"):
        raise ValidationError("Engine assessment is not enabled.")
    profile = settings.TRIAGE_ENGINE_PROFILE
    digest = settings.TRIAGE_ENGINE_CONFIG_SHA256
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", profile):
        raise ValidationError("Configure an approved engine profile.")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValidationError("Configure the approved engine configuration digest.")
    if not re.fullmatch(
        r"[A-Za-z0-9._~-]{32,256}", settings.TRIAGE_ENGINE_SERVICE_TOKEN
    ):
        raise ValidationError("Configure a strong engine service token.")
    url = urlsplit(settings.TRIAGE_ENGINE_URL)
    try:
        port = url.port
    except ValueError as exc:
        raise ValidationError("The engine URL has an invalid port.") from exc
    if (
        url.scheme != "http"
        or url.hostname != "127.0.0.1"
        or not port
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
    ):
        raise ValidationError(
            "The engine must use a loopback-only HTTP URL with a port."
        )
    return settings.TRIAGE_ENGINE_URL.rstrip("/"), profile, digest


def _policy(version: int | None = None) -> TriagePolicy:
    policy: TriagePolicy | None = TriagePolicy.objects.filter(
        status=TriagePolicy.Status.ACTIVE
    ).first()
    if (
        policy is None
        or (version is not None and policy.version != version)
        or policy.taxonomy_snapshot is None
        or policy.taxonomy_snapshot != snapshot_taxonomy()
    ):
        raise ValidationError(
            "An active policy with an unchanged taxonomy is required."
        )
    return policy


def _payload(submission: ReportSubmission, profile: str) -> dict[str, Any]:
    if not submission.description.strip() or len(submission.description) > 10_000:
        raise ValidationError("The report description exceeds the engine's limits.")
    if len(submission.location_description) > 500:
        raise ValidationError(
            "The location description exceeds the engine's 500-character limit."
        )
    location: dict[str, Any] = {}
    if submission.location_description:
        location["free_text"] = submission.location_description
    if submission.latitude is not None and submission.longitude is not None:
        location["latitude"] = float(submission.latitude)
        location["longitude"] = float(submission.longitude)
    return {
        "profile_id": profile,
        "description": submission.description,
        "location": location or None,
        "allow_degraded_on_ai_error": True,
    }


@transaction.atomic
def request_assessment(submission_id: int, reviewer: Employee) -> TriageEngineJob:
    """Queue one assessment, preserving the approved context and input fingerprint."""
    if reviewer.pk is None or not reviewer.user.has_perm(
        "intake.review_reportsubmission"
    ):
        raise ValidationError("An authorized reviewer is required.")
    _, profile, digest = _configuration()
    policy = _policy()
    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.triage_state != ReportSubmission.TriageState.NEEDS_REVIEW:
        raise ValidationError("Only reports awaiting review can be assessed.")
    payload = _payload(submission, profile)
    try:
        with transaction.atomic():
            return TriageEngineJob.objects.create(
                submission=submission,
                requested_by=reviewer,
                policy_version=policy.version,
                profile=profile,
                config_digest=digest,
                input_digest=_digest(payload),
                visible_to_reviewers=settings.TRIAGE_ENGINE_MODE == "review",
            )
    except IntegrityError as exc:
        raise ValidationError(
            "An assessment is already pending for this report."
        ) from exc


def reviewable_result(job: TriageEngineJob, submission: ReportSubmission) -> bool:
    """Keep shadow, stale and superseded results out of the review interface."""
    if (
        settings.TRIAGE_ENGINE_MODE != "review"
        or not job.visible_to_reviewers
        or job.status != TriageEngineJob.Status.COMPLETED
        or submission.triage_state != ReportSubmission.TriageState.NEEDS_REVIEW
    ):
        return False
    try:
        _, profile, digest = _configuration()
        _policy(job.policy_version)
        return (profile, digest) == (job.profile, job.config_digest) and _digest(
            _payload(submission, profile)
        ) == job.input_digest
    except ValidationError:
        return False


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _json_request(url: str, payload: dict[str, Any] | None = None) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(  # noqa: S310 - URL is built from the validated loopback origin.
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {settings.TRIAGE_ENGINE_SERVICE_TOKEN}",
        },
    )
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(request, timeout=35) as response:
            body = response.read(MAX_RESPONSE_BYTES + 1)
        if len(body) > MAX_RESPONSE_BYTES:
            raise EngineError("The engine response exceeded the size limit.")
        return json.loads(body)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise EngineError("The engine could not return a valid response.") from exc


def _evaluate(
    base_url: str, job: TriageEngineJob, payload: dict[str, Any]
) -> dict[str, Any]:
    config = _json_request(f"{base_url}/api/v1/configs/{job.profile}")
    if not isinstance(config, dict) or _digest(config) != job.config_digest:
        raise EngineError(
            "The engine configuration does not match the approved digest."
        )
    result = _json_request(f"{base_url}/api/v1/triage", payload)
    if not isinstance(result, dict) or result.get("profile_used") != job.profile:
        raise EngineError("The engine returned an invalid profile or response.")
    if result.get("status") not in ("completed", "abstained", "degraded"):
        raise EngineError("The engine returned an unrecognized status.")
    for key in (
        "category_recommendation",
        "priority_recommendation",
        "routing_recommendation",
        "safety_assessment",
        "evidence_and_reasoning",
        "uncertainty_assessment",
        "human_review",
        "provider_metadata",
    ):
        if not isinstance(result.get(key), dict):
            raise EngineError("The engine response is missing required information.")
    if not isinstance(result.get("missing_information"), list):
        raise EngineError("The engine response is missing required information.")
    if not isinstance(result["safety_assessment"].get("escalation_triggered"), bool):
        raise EngineError("The engine response has an invalid safety assessment.")
    return result


def process_job(job_id: int) -> bool:
    """Claim a job with a lease; never hold database locks during engine calls."""
    lease = uuid4()
    now = timezone.now()
    eligible = Q(status=TriageEngineJob.Status.PENDING) | Q(
        status=TriageEngineJob.Status.PROCESSING,
        started_at__lt=now - timedelta(minutes=LEASE_MINUTES),
    )
    claimed = TriageEngineJob.objects.filter(eligible, pk=job_id).update(
        status=TriageEngineJob.Status.PROCESSING, lease=lease, started_at=now
    )
    if not claimed:
        return False
    job = TriageEngineJob.objects.select_related("submission").get(pk=job_id)
    try:
        base_url, profile, digest = _configuration()
        if (profile, digest) != (job.profile, job.config_digest):
            raise ValidationError("The approved engine configuration has changed.")
        _policy(job.policy_version)
        if job.submission.triage_state != ReportSubmission.TriageState.NEEDS_REVIEW:
            raise ValidationError("The report is no longer awaiting review.")
        payload = _payload(job.submission, profile)
        if _digest(payload) != job.input_digest:
            raise ValidationError(
                "The report changed after the assessment was requested."
            )
        result = _evaluate(base_url, job, payload)
        with transaction.atomic():
            submission = ReportSubmission.objects.select_for_update().get(
                pk=job.submission_id
            )
            _, current_profile, current_digest = _configuration()
            _policy(job.policy_version)
            if (
                submission.triage_state != ReportSubmission.TriageState.NEEDS_REVIEW
                or (current_profile, current_digest) != (job.profile, job.config_digest)
                or _digest(_payload(submission, profile)) != job.input_digest
            ):
                raise ValidationError(
                    "The report changed before the assessment completed."
                )
            saved = TriageEngineJob.objects.filter(pk=job_id, lease=lease).update(
                status=TriageEngineJob.Status.COMPLETED,
                result=result,
                finished_at=timezone.now(),
                error="",
            )
            if (
                saved
                and job.visible_to_reviewers
                and settings.TRIAGE_ENGINE_MODE == "review"
                and result["safety_assessment"]["escalation_triggered"]
                and not submission.urgent_review
            ):
                submission.urgent_review = True
                submission.save(update_fields=("urgent_review",))
    except (EngineError, ValidationError) as exc:
        logger.warning("Engine assessment %s failed: %s", job_id, exc)
        TriageEngineJob.objects.filter(pk=job_id, lease=lease).update(
            status=TriageEngineJob.Status.FAILED,
            error=str(exc)[:200],
            finished_at=timezone.now(),
        )
    return True
