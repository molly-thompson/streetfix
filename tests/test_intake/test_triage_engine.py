"""Tests for optional engine assessments and the reviewer dashboard."""

from collections.abc import Callable
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone

from employees.organisation_models import Employee
from intake.models import ReportSubmission, TriageEngineJob, TriagePolicy
from intake.services.triage.engine import (
    process_job,
    request_assessment,
    reviewable_result,
)
from intake.services.triage.taxonomy import snapshot_taxonomy
from site_settings.models import SiteConfiguration, ThemeSettings

pytestmark = pytest.mark.django_db

CONFIG = {"profile_id": "test", "example": "approved"}


@pytest.fixture
def engine_settings() -> Any:
    """Enable an isolated test configuration."""
    SiteConfiguration.objects.update_or_create(
        pk=1,
        defaults={
            "triage_engine_mode": "review",
            "triage_engine_configuration": CONFIG,
        },
    )
    with override_settings(
        TRIAGE_ENGINE_URL="http://127.0.0.1:8001",
        TRIAGE_ENGINE_SERVICE_TOKEN="x" * 32,
    ):
        yield


@pytest.fixture
def reviewer(make_employee: Callable[..., Employee]) -> Employee:
    """Create an employee authorized to review."""
    employee = make_employee()
    employee.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    return employee


@pytest.fixture
def active_policy() -> TriagePolicy:
    """Create a policy snapshot for assessment."""
    policy = TriagePolicy.objects.create(version=1, name="Test")
    TriagePolicy._base_manager.filter(pk=policy.pk).update(
        status="ACTIVE",
        activated_at=timezone.now(),
        taxonomy_snapshot=snapshot_taxonomy(),
    )
    policy.refresh_from_db()
    return policy


@pytest.fixture
def submission() -> ReportSubmission:
    """Create a report awaiting review."""
    return ReportSubmission.objects.create(
        description="A broken light",
        updates_requested=False,
        triage_state="NEEDS_REVIEW",
    )


def engine_result() -> dict[str, Any]:
    """Build a minimal valid engine response."""
    return {
        "profile_used": "test",
        "status": "completed",
        "category_recommendation": {"primary_category_name": "Lighting"},
        "priority_recommendation": {"priority_name": "Urgent", "rationale": "Review"},
        "routing_recommendation": {"team_name": "Lighting team", "rationale": "Review"},
        "safety_assessment": {"escalation_triggered": False},
        "evidence_and_reasoning": {"reasoning_summary": "Reported damage"},
        "uncertainty_assessment": {},
        "human_review": {"required": True},
        "provider_metadata": {},
        "missing_information": [],
    }


def test_reviewers_queue_assessment_and_view_advice(
    client: Client,
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """Results are separate from decisions and visible only to authorized reviewers."""
    url = reverse("intake:request_engine_assessment", args=[submission.pk])
    assert client.post(url).status_code == 302
    client.force_login(reviewer.user)
    assert client.get(url).status_code == 405
    assert client.post(url).status_code == 302
    job = submission.engine_jobs.get()
    with patch(
        "intake.services.triage.engine._json_request",
        return_value=engine_result(),
    ) as request:
        assert process_job(job.pk)
    assert request.call_args.args[1] == {
        "configuration": CONFIG,
        "report": {
            "profile_id": "test",
            "description": "A broken light",
            "location": None,
            "allow_degraded_on_ai_error": True,
        },
    }
    job.refresh_from_db()
    submission.refresh_from_db()
    assert job.status == "COMPLETED"
    assert submission.triage_state == "NEEDS_REVIEW"
    assert submission.work_item is None
    response = client.get(reverse("intake:review_detail", args=[submission.pk]))
    assert b"Lighting team" in response.content
    assert b"not confirmed priority or urgency" in response.content
    assert "no-store" in response.headers["Cache-Control"]
    dashboard = client.get(reverse("intake:review_queue"))
    assert b"Triage dashboard" in dashboard.content
    assert b"Completed" in dashboard.content


def test_review_dashboard_combines_both_assessments(
    client: Client,
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """Both reviewer tools remain available, including after a form error."""
    config = SiteConfiguration.objects.get(pk=1)
    config.duplicate_matching_enabled = True
    config.save()
    client.force_login(reviewer.user)
    detail_url = reverse("intake:review_detail", args=[submission.pk])
    detail = client.get(detail_url)
    assert b"Assess matching signals" in detail.content
    assert b"Request assessment" in detail.content
    assert detail.content.count(b"Correct location</h2>") == 1
    assert detail.content.count(b"Triage history</h2>") == 1

    invalid = client.post(
        reverse("intake:correct_location", args=[submission.pk]),
        {"latitude": "1", "longitude": "2", "reason": ""},
    )
    assert invalid.status_code == 400
    assert b"Assess matching signals" in invalid.content
    assert b"Request assessment" in invalid.content


def test_shadow_results_stay_hidden_after_enabling_review(
    client: Client,
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """Switching modes cannot expose shadow results to a reviewer."""
    config = SiteConfiguration.objects.get(pk=1)
    config.triage_engine_mode = "shadow"
    config.save()
    job = request_assessment(submission.pk, reviewer)
    with patch(
        "intake.services.triage.engine._json_request",
        return_value=engine_result(),
    ):
        process_job(job.pk)
    config.triage_engine_mode = "review"
    config.save()
    job.refresh_from_db()
    assert not reviewable_result(job, submission)
    client.force_login(reviewer.user)
    content = client.get(reverse("intake:review_detail", args=[submission.pk])).content
    assert b"Lighting team" not in content


def test_config_drift_and_changed_report_fail_closed(
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """Changed database configuration never results in a recommendation."""
    job = request_assessment(submission.pk, reviewer)
    config = SiteConfiguration.objects.get(pk=1)
    config.triage_engine_configuration = {"profile_id": "test", "example": "changed"}
    config.save()
    with patch("intake.services.triage.engine._json_request") as request:
        process_job(job.pk)
    job.refresh_from_db()
    assert job.status == "FAILED"
    assert job.result is None
    request.assert_not_called()
    config.triage_engine_configuration = CONFIG
    config.save()
    next_job = request_assessment(submission.pk, reviewer)
    submission.description = "Changed"
    submission.save(update_fields=("description",))
    with patch("intake.services.triage.engine._json_request") as request:
        process_job(next_job.pk)
    next_job.refresh_from_db()
    assert next_job.status == "FAILED"
    request.assert_not_called()


def test_late_result_is_discarded(
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """A reviewer decision made during the call wins over the engine."""
    job = request_assessment(submission.pk, reviewer)

    def evaluate(*args: Any) -> dict[str, Any]:
        ReportSubmission.objects.filter(pk=submission.pk).update(
            triage_state="OUT_OF_SCOPE"
        )
        return engine_result()

    with patch("intake.services.triage.engine._evaluate", side_effect=evaluate):
        process_job(job.pk)
    job.refresh_from_db()
    assert job.status == "FAILED"
    assert job.result is None


def test_result_finishing_in_shadow_mode_stays_hidden(
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """A mode switch during processing cannot expose a shadow result later."""
    job = request_assessment(submission.pk, reviewer)

    def evaluate(*args: Any) -> dict[str, Any]:
        config = SiteConfiguration.objects.get(pk=1)
        config.triage_engine_mode = "shadow"
        config.save()
        return engine_result()

    with patch("intake.services.triage.engine._evaluate", side_effect=evaluate):
        process_job(job.pk)
    job.refresh_from_db()
    assert job.status == "COMPLETED"
    assert not job.visible_to_reviewers
    config = SiteConfiguration.objects.get(pk=1)
    config.triage_engine_mode = "review"
    config.save()
    assert not reviewable_result(job, submission)


def test_completed_result_is_hidden_when_configuration_changes(
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """A recommendation cannot be presented under a different profile."""
    job = request_assessment(submission.pk, reviewer)
    with patch(
        "intake.services.triage.engine._json_request", return_value=engine_result()
    ):
        process_job(job.pk)
    job.refresh_from_db()
    assert reviewable_result(job, submission)
    config = SiteConfiguration.objects.get(pk=1)
    config.triage_engine_configuration = {"profile_id": "test", "example": "changed"}
    config.save()
    assert not reviewable_result(job, submission)


def test_request_rejects_duplicate_and_oversized_location(
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """Concurrent requests and unsupported input are explicit failures."""
    request_assessment(submission.pk, reviewer)
    with pytest.raises(ValidationError, match="already pending"):
        request_assessment(submission.pk, reviewer)
    TriageEngineJob.objects.update(status="FAILED")
    submission.location_description = "x" * 501
    submission.save(update_fields=("location_description",))
    with pytest.raises(ValidationError, match="500-character"):
        request_assessment(submission.pk, reviewer)


def test_expired_lease_is_recovered(
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """A crashed worker's old claim can be picked up again."""
    job = request_assessment(submission.pk, reviewer)
    TriageEngineJob.objects.filter(pk=job.pk).update(
        status="PROCESSING", started_at=timezone.now() - timedelta(minutes=6)
    )
    with patch(
        "intake.services.triage.engine._json_request",
        return_value=engine_result(),
    ):
        assert process_job(job.pk)
    job.refresh_from_db()
    assert job.status == "COMPLETED"


@pytest.mark.parametrize(("mode", "expected"), [("review", True), ("shadow", False)])
def test_safety_escalation_only_flags_visible_assessments(
    engine_settings: Any,
    active_policy: TriagePolicy,
    reviewer: Employee,
    submission: ReportSubmission,
    mode: str,
    expected: bool,
) -> None:
    """Safety alerts highlight the queue without affecting shadow comparisons."""
    result = engine_result()
    result["safety_assessment"]["escalation_triggered"] = True
    config = SiteConfiguration.objects.get(pk=1)
    config.triage_engine_mode = mode
    config.save()
    job = request_assessment(submission.pk, reviewer)
    with patch("intake.services.triage.engine._json_request", return_value=result):
        process_job(job.pk)
    submission.refresh_from_db()
    assert submission.urgent_review is expected
    assert submission.work_item is None


def test_disabled_and_unauthorized_requests_do_not_queue(
    client: Client,
    reviewer: Employee,
    submission: ReportSubmission,
) -> None:
    """The endpoint requires permission and never bypasses the deployment flag."""
    url = reverse("intake:request_engine_assessment", args=[submission.pk])
    reviewer.user.user_permissions.clear()
    client.force_login(reviewer.user)
    assert client.post(url).status_code == 403
    reviewer.user.user_permissions.add(
        Permission.objects.get(codename="review_reportsubmission")
    )
    client.force_login(reviewer.user)
    assert client.post(url).status_code == 302
    assert not submission.engine_jobs.exists()


def test_dashboard_uses_database_branding_and_live_configuration(
    client: Client,
    engine_settings: Any,
    reviewer: Employee,
    theme_settings: ThemeSettings,
) -> None:
    """The dashboard follows the stored theme and mode without a restart."""
    theme_settings.site_name = "Example services"
    theme_settings.primary_color = "#1d4ed8"
    theme_settings.save()
    client.force_login(reviewer.user)
    url = reverse("intake:review_queue")
    response = client.get(url)
    assert b"Example services" in response.content
    assert b"--theme-primary: #1d4ed8;" in response.content
    assert b"Decision support is available" in response.content
    config = SiteConfiguration.objects.get(pk=1)
    config.triage_engine_mode = "off"
    config.save()
    assert b"Decision support is disabled" in client.get(url).content


def test_enabled_configuration_requires_a_profile() -> None:
    """An administrator cannot enable decision support with an empty profile."""
    config = SiteConfiguration(triage_engine_mode="review")
    with pytest.raises(ValidationError, match="approved profile"):
        config.full_clean()
