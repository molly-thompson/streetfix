"""Tests for bounded, database-configured triage policy rules."""

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from employees.organisation_models import Department, IssueType
from intake.models import TriagePolicy, TriagePolicyRule

pytestmark = pytest.mark.django_db


def test_policy_rule_requires_evidence_and_an_outcome_for_its_target() -> None:
    """Unconditional rules and codes for the wrong field are rejected."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    rule = TriagePolicyRule(
        policy=policy,
        name="Impact",
        target=TriagePolicyRule.Target.PRIORITY,
        outcome_code="ROUTINE",
    )
    with pytest.raises(ValidationError):
        rule.full_clean()
    with pytest.raises(IntegrityError), transaction.atomic():
        rule.save()
    rule.impact = "SIGNIFICANT"
    rule.outcome_code = "HIGH"
    rule.full_clean()
    rule.save()


def test_sensitive_modifier_requires_relevant_issue_and_time_for_urgency() -> None:
    """Sensitive content is issue-specific and not urgency evidence alone."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    department = Department.objects.create(name="Facilities")
    issue = IssueType.objects.create(
        department=department, name="Damage", code="DAMAGE"
    )
    rule = TriagePolicyRule(
        policy=policy,
        name="Sensitive",
        issue_type=issue,
        sensitive_content="YES",
        target=TriagePolicyRule.Target.URGENCY,
        outcome_code="URGENT",
    )
    with pytest.raises(ValidationError):
        rule.full_clean()
    issue.sensitive_content_enabled = True
    issue.save(update_fields=("sensitive_content_enabled",))
    with pytest.raises(IntegrityError), transaction.atomic():
        rule.save()
    rule.time_sensitivity = "PROMPT"
    rule.full_clean()
    rule.save()


def test_only_one_policy_can_be_active() -> None:
    """Database constraints reject competing active policy versions."""
    first = TriagePolicy.objects.create(version=1, name="First")
    second = TriagePolicy.objects.create(version=2, name="Second")
    TriagePolicy._base_manager.filter(pk=first.pk).update(
        status="ACTIVE", activated_at=timezone.now()
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        TriagePolicy._base_manager.filter(pk=second.pk).update(
            status="ACTIVE", activated_at=timezone.now()
        )


@pytest.mark.parametrize("phrases", ["gas leak", [""], [1], ["Gas leak", " gas leak "]])
def test_policy_rejects_malformed_urgent_review_cues(phrases: object) -> None:
    """Cue configuration is bounded literal text, not executable patterns."""
    policy = TriagePolicy(version=1, name="Draft", urgent_review_phrases=phrases)
    with pytest.raises(ValidationError) as error:
        policy.clean()
    assert "urgent_review_phrases" in error.value.message_dict


@pytest.mark.parametrize(
    "labels",
    [
        {"unknown_field": {}},
        {"reported_impact": {"choices": {"EXTRA": "Extra"}}},
        {"reported_impact": {"choices": {"SEVERE": ""}}},
        {"reported_impact": {"label": []}},
        {"reported_impact": {"unexpected": "value"}},
    ],
)
def test_policy_rejects_unbounded_evidence_label_configuration(labels: object) -> None:
    """Label settings cannot add evidence factors or change their codes."""
    policy = TriagePolicy(version=1, name="Draft", evidence_labels=labels)
    with pytest.raises(ValidationError) as error:
        policy.clean()
    assert "evidence_labels" in error.value.message_dict
