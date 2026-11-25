"""Coordinate deterministic triage and preserve reviewable proposals."""

from dataclasses import asdict

from django.core.exceptions import ValidationError
from django.db import transaction

from intake.models import (
    ReportSubmission,
    TriageAttempt,
    TriagePolicy,
    TriagePolicyRule,
)
from intake.services.review import request_review
from intake.services.triage.geography import (
    Coverage,
    evaluate_coverage,
    parse_service_area,
)
from intake.services.triage.results import Evidence
from intake.services.triage.rules import evaluate_field
from intake.services.triage.taxonomy import snapshot_taxonomy
from intake.services.triage.urgent import (
    matching_urgent_phrases,
    validate_urgent_phrases,
)


@transaction.atomic
def triage_submission(submission_id: int) -> None:
    """Assess one received report, retaining all proposals for human review."""
    submission = ReportSubmission.objects.select_for_update().get(pk=submission_id)
    if submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW:
        return
    if submission.triage_state != ReportSubmission.TriageState.RECEIVED:
        raise ValidationError("Only received submissions can be triaged.")

    if (
        submission.reported_time_sensitivity
        == ReportSubmission.ReportedTimeSensitivity.IMMEDIATE
    ):
        submission.urgent_review = True
        submission.save(update_fields=("urgent_review",))

    policy = TriagePolicy.objects.filter(status=TriagePolicy.Status.ACTIVE).first()
    if policy is None:
        request_review(submission_id, reason="No approved triage policy is available.")
        return

    try:
        phrases = validate_urgent_phrases(policy.urgent_review_phrases)
    except ValidationError:
        request_review(
            submission_id,
            reason="The active triage policy is invalid.",
            policy_version=str(policy.version),
        )
        return

    urgent_cues = matching_urgent_phrases(submission.description, phrases)
    if urgent_cues and not submission.urgent_review:
        submission.urgent_review = True
        submission.save(update_fields=("urgent_review",))
    if (
        policy.taxonomy_snapshot is None
        or policy.taxonomy_snapshot != snapshot_taxonomy()
    ):
        request_review(
            submission_id,
            reason="The policy taxonomy is missing or has changed; review is required.",
            policy_version=str(policy.version),
        )
        return
    rules = list(policy.rules.select_related("issue_type").all())
    try:
        area = (
            parse_service_area(policy.service_area)
            if policy.service_area is not None
            else None
        )
        for rule in rules:
            rule.full_clean()
    except ValidationError:
        request_review(
            submission_id,
            reason="The active triage policy is invalid.",
            policy_version=str(policy.version),
        )
        return

    evidence = Evidence(
        issue_type_id=submission.reported_issue_type_id,
        impact=submission.reported_impact,
        time_sensitivity=submission.reported_time_sensitivity,
        sensitive_content=submission.reported_sensitive_content,
    )
    outcomes = {
        target.lower(): asdict(evaluate_field(rules, target=target, evidence=evidence))
        for target in (
            TriagePolicyRule.Target.PRIORITY,
            TriagePolicyRule.Target.URGENCY,
        )
    }
    coverage = evaluate_coverage(
        area,
        float(submission.latitude) if submission.latitude is not None else None,
        float(submission.longitude) if submission.longitude is not None else None,
    )
    outcomes["geographic_coverage"] = {
        "state": "observed"
        if coverage in (Coverage.INSIDE, Coverage.OUTSIDE)
        else "ambiguous",
        "value": coverage.value,
    }
    TriageAttempt.objects.create(
        submission=submission,
        stage=TriageAttempt.Stage.RULES,
        policy_version=str(policy.version),
        field_outcomes=outcomes,
        evidence={"source": "reporter", **asdict(evidence), "urgent_cues": urgent_cues},
        decision="PROPOSED",
        reason="Reporter-provided evidence requires human review.",
    )
    request_review(
        submission_id,
        reason="Automated proposals require human review.",
        policy_version=str(policy.version),
    )
