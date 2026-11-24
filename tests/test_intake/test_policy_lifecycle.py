"""Tests for approval and immutability of triage policies."""

from collections.abc import Callable

import pytest
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError

from employees.organisation_models import Department, Employee, IssueType
from intake.models import TriagePolicy, TriagePolicyRule, TriagePolicyScenario
from intake.services.triage.policy import activate_policy
from intake.services.triage.taxonomy import snapshot_taxonomy

pytestmark = pytest.mark.django_db


@pytest.fixture
def approver(make_employee: Callable[..., Employee]) -> Employee:
    """Provide an employee authorized to activate a policy."""
    employee = make_employee()
    employee.user.user_permissions.add(
        Permission.objects.get(codename="activate_triagepolicy")
    )
    return employee


def draft_with_example(version: int) -> TriagePolicy:
    """Prepare a draft with a matching example."""
    policy = TriagePolicy.objects.create(version=version, name="Draft")
    TriagePolicyRule.objects.create(
        policy=policy,
        name="Impact",
        impact="SIGNIFICANT",
        target="PRIORITY",
        outcome_code="HIGH",
    )
    TriagePolicyScenario.objects.create(
        policy=policy,
        name="Significant",
        impact="SIGNIFICANT",
        priority_state="determined",
        priority_code="HIGH",
        urgency_state="ambiguous",
    )
    return policy


def test_activation_requires_permission_and_passing_examples(
    approver: Employee, make_employee: Callable[..., Employee]
) -> None:
    """A policy cannot become active without authorization and valid examples."""
    draft = draft_with_example(1)
    with pytest.raises(ValidationError):
        activate_policy(draft.pk, approver=make_employee("not-approver"))
    scenario = draft.scenarios.get()
    scenario.priority_code = "LOW"
    scenario.save()
    with pytest.raises(ValidationError):
        activate_policy(draft.pk, approver=approver)
    draft.refresh_from_db()
    assert draft.status == "DRAFT"
    scenario.priority_code = "HIGH"
    scenario.save()
    activate_policy(draft.pk, approver=approver)
    draft.refresh_from_db()
    assert draft.status == "ACTIVE"
    assert draft.activated_by == approver
    assert draft.activated_at is not None


def test_new_version_retires_the_previous_active_policy(approver: Employee) -> None:
    """Only one approved version is active; old definitions remain intact."""
    first = draft_with_example(1)
    second = draft_with_example(2)
    activate_policy(first.pk, approver=approver)
    activate_policy(second.pk, approver=approver)
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == "RETIRED"
    assert second.status == "ACTIVE"
    assert first.rules.count() == 1


def test_activated_policy_and_children_cannot_be_mutated(approver: Employee) -> None:
    """Model and ordinary bulk operations cannot change approved definitions."""
    policy = draft_with_example(1)
    rule = policy.rules.get()
    scenario = policy.scenarios.get()
    activate_policy(policy.pk, approver=approver)
    policy.refresh_from_db()
    policy.name = "Changed"
    with pytest.raises(ValidationError):
        policy.save()
    with pytest.raises(ValidationError):
        policy.delete()
    rule.impact = "LIMITED"
    with pytest.raises(ValidationError):
        rule.save()
    with pytest.raises(ValidationError):
        scenario.delete()
    with pytest.raises(ValidationError):
        TriagePolicyRule.objects.filter(pk=rule.pk).update(impact="LIMITED")
    with pytest.raises(ValidationError):
        TriagePolicy.objects.filter(pk=policy.pk).delete()
    with pytest.raises(ValidationError):
        TriagePolicyRule.objects.create(
            policy=policy,
            name="New rule",
            impact="LIMITED",
            target="PRIORITY",
            outcome_code="LOW",
        )


def test_activation_captures_taxonomy_and_routing(approver: Employee) -> None:
    """The approved version retains the issue hierarchy and department mapping."""
    department = Department.objects.create(name="Facilities")
    category = IssueType.objects.create(
        name="Parks", code="PARKS", kind=IssueType.Kind.CATEGORY
    )
    IssueType.objects.create(
        name="Damage", code="DAMAGE", parent=category, department=department
    )
    policy = draft_with_example(1)
    activate_policy(policy.pk, approver=approver)
    policy.refresh_from_db()
    original = policy.taxonomy_snapshot
    assert original == snapshot_taxonomy()
    department.name = "Changed"
    department.save(update_fields=("name",))
    assert original != snapshot_taxonomy()
    policy.refresh_from_db()
    assert policy.taxonomy_snapshot == original
