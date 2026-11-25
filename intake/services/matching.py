"""Prepare and record optional, human-reviewed duplicate assessments."""

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import OuterRef, Subquery

from employees.organisation_models import Employee
from employees.work_models import WorkItem
from intake.models import ReportSubmission, TriageAttempt, TriagePolicy
from intake.services.duplicates import DuplicateSearch, duplicate_candidates
from intake.services.reportmatch.engine import detect_duplicates
from intake.services.reportmatch.models import (
    DuplicateDetectionRequest,
    GenericReport,
    MatchingConfig,
    MatchingThresholds,
    ReportLocation,
)

MATCH_DECISION = "DUPLICATE_ASSESSMENT"
MATCH_ENGINE_VERSION = "reportmatch-deterministic-1"


@dataclass(frozen=True)
class MatchingInputs:
    """A bounded candidate search and its detector inputs."""

    search: DuplicateSearch
    request: DuplicateDetectionRequest
    config: MatchingConfig
    policy_version: str
    fingerprint: str


def matching_inputs(
    submission: ReportSubmission, search: DuplicateSearch
) -> MatchingInputs:
    """Map available original reports without sending contact or photo data."""
    if submission.triage_state != ReportSubmission.TriageState.NEEDS_REVIEW:
        raise ValidationError("Matching is available only for reports in review.")
    if len(submission.description.strip()) < 3:
        raise ValidationError("The report description is too short to assess.")
    policy = TriagePolicy.objects.filter(status=TriagePolicy.Status.ACTIVE).first()
    if (
        policy is None
        or search.distance_m is None
        or search.age_days is None
        or submission.latitude is None
        or submission.longitude is None
        or policy.duplicate_distance_m != search.distance_m
        or policy.duplicate_age_days != search.age_days
    ):
        raise ValidationError(
            "Matching needs a map pin and an active duplicate-search policy."
        )

    original_id = (
        ReportSubmission.objects.filter(work_item_id=OuterRef("pk"))
        .order_by("submitted_at", "pk")
        .values("pk")[:1]
    )
    ids = list(
        WorkItem.objects.filter(pk__in=[c.work.pk for c in search.candidates])
        .annotate(original_id=Subquery(original_id))
        .values_list("original_id", flat=True)
    )
    originals = {
        report.work_item_id: report
        for report in ReportSubmission.objects.filter(pk__in=ids)
    }

    def category_id(report: ReportSubmission) -> str | None:
        if report.reported_issue_type_id and not report.other_selected:
            return str(report.reported_issue_type_id)
        return None

    incoming = GenericReport(
        id=f"submission:{submission.pk}",
        description=submission.description,
        category=category_id(submission),
        location=ReportLocation(
            latitude=float(submission.latitude),
            longitude=float(submission.longitude),
            locationDescription=submission.location_description or None,
        ),
        reportedAt=submission.submitted_at.isoformat(),
    )
    reports = []
    for candidate in search.candidates:
        original = originals.get(candidate.work.pk)
        if original is None or len(original.description.strip()) < 3:
            continue
        reports.append(
            GenericReport(
                id=f"work:{candidate.work.pk}",
                description=original.description,
                category=str(candidate.work.issue_type_id),
                location=ReportLocation(
                    latitude=float(candidate.work.latitude),
                    longitude=float(candidate.work.longitude),
                    locationDescription=original.location_description or None,
                ),
                reportedAt=original.submitted_at.isoformat(),
                status=candidate.work.status.code,
            )
        )
    request = DuplicateDetectionRequest(
        incomingReport=incoming, existingReports=reports
    )
    config = MatchingConfig(
        thresholds=MatchingThresholds.model_validate(
            {
                "maxDuplicateDistanceMeters": search.distance_m,
                "relatedDistanceMeters": search.distance_m,
                "duplicateTimeWindowHours": search.age_days * 24,
                "recurringMinGapHours": search.age_days * 24,
            }
        )
    )
    fingerprint_data = {
        "request": request.model_dump(),
        "config": config.model_dump(),
        "policy_version": policy.version,
        "engine_version": MATCH_ENGINE_VERSION,
        "candidate_ids": [c.work.pk for c in search.candidates],
        "truncated": search.truncated,
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_data, sort_keys=True).encode()
    ).hexdigest()
    return MatchingInputs(search, request, config, str(policy.version), fingerprint)


@transaction.atomic
def assess_duplicates(submission_id: int, *, reviewer: Employee) -> None:
    """Record a fresh advisory assessment, without changing the report."""
    if reviewer.pk is None or not reviewer.user.has_perm(
        "intake.review_reportsubmission"
    ):
        raise ValidationError("An authorized reviewer is required.")
    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    inputs = matching_inputs(submission, duplicate_candidates(submission))
    result = detect_duplicates(inputs.request, inputs.config)
    assessments = [
        {
            "work_item_id": int(assessment.candidateReportId.removeprefix("work:")),
            "classification": assessment.classification,
            "label": assessment.classificationLabel,
            "explanation": assessment.explanation,
            "uncertainty": assessment.uncertaintyNotes,
            "contradictions": assessment.contradictions,
            "signals": [
                {
                    "label": signal.label,
                    "status": signal.status,
                    "summary": signal.summary,
                }
                for signal in assessment.signalBreakdown.values()
            ],
        }
        for assessment in result.assessments
    ]
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.RULES,
        policy_version=inputs.policy_version,
        decision=MATCH_DECISION,
        reviewer=reviewer,
        reason="Reviewer requested an advisory duplicate assessment.",
        evidence={
            "request_id": result.requestId,
            "engine_version": MATCH_ENGINE_VERSION,
            "fingerprint": inputs.fingerprint,
            "config": inputs.config.model_dump(),
            "candidate_ids": [c.work.pk for c in inputs.search.candidates],
            "truncated": inputs.search.truncated,
            "assessments": assessments,
        },
    )


def current_assessments(
    submission: ReportSubmission, search: DuplicateSearch
) -> tuple[dict[int, dict[str, Any]], str]:
    """Return assessments only while their candidate evidence remains current."""
    try:
        inputs = matching_inputs(submission, search)
    except ValidationError as exc:
        return {}, " ".join(exc.messages)
    attempt = (
        submission.triage_attempts.filter(decision=MATCH_DECISION)
        .order_by("-created_at", "-pk")
        .first()
    )
    if attempt is None:
        return {}, "Run an assessment to see advisory matching signals."
    if attempt.evidence.get("fingerprint") != inputs.fingerprint:
        return {}, "The report or candidate work has changed. Run the assessment again."
    assessments = {
        item["work_item_id"]: item for item in attempt.evidence["assessments"]
    }
    return assessments, ""
