"""Tests for preparing policy drafts in the admin."""

from collections.abc import Callable

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from employees.organisation_models import Employee
from intake.models import (
    ReportSubmission,
    TriageAttempt,
    TriagePolicy,
    TriagePolicyRule,
    TriagePolicyScenario,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_client(client: Client) -> Client:
    """Provide an administrative user."""
    user = get_user_model().objects.create_superuser(
        username="policy-admin", email="policy-admin@example.test", password=None
    )
    client.force_login(user)
    return client


def test_admin_can_edit_draft_but_cannot_set_its_status(admin_client: Client) -> None:
    """Publishing is not possible through the draft editor."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    response = admin_client.post(
        reverse("admin:intake_triagepolicy_change", args=[policy.pk]),
        {
            "version": "1",
            "name": "Revised draft",
            "status": "ACTIVE",
            "service_area": "",
            "evidence_labels": "{}",
            "rules-TOTAL_FORMS": "0",
            "rules-INITIAL_FORMS": "0",
            "rules-MIN_NUM_FORMS": "0",
            "rules-MAX_NUM_FORMS": "1000",
            "scenarios-TOTAL_FORMS": "0",
            "scenarios-INITIAL_FORMS": "0",
            "scenarios-MIN_NUM_FORMS": "0",
            "scenarios-MAX_NUM_FORMS": "1000",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    policy.refresh_from_db()
    assert policy.name == "Revised draft"
    assert policy.status == "DRAFT"


def test_admin_cannot_edit_an_active_policy_or_its_rules(admin_client: Client) -> None:
    """Previously activated definitions cannot be changed through the editor."""
    policy = TriagePolicy.objects.create(version=1, name="Approved")
    rule = TriagePolicyRule.objects.create(
        policy=policy,
        name="Impact",
        impact="SIGNIFICANT",
        target="PRIORITY",
        outcome_code="HIGH",
    )
    TriagePolicy._base_manager.filter(pk=policy.pk).update(
        status="ACTIVE", activated_at=timezone.now()
    )
    response = admin_client.post(
        reverse("admin:intake_triagepolicy_change", args=[policy.pk]),
        {
            "version": "2",
            "name": "Tampered",
            "status": "DRAFT",
            "service_area": "",
            "evidence_labels": "{}",
            "rules-TOTAL_FORMS": "1",
            "rules-INITIAL_FORMS": "1",
            "rules-MIN_NUM_FORMS": "0",
            "rules-MAX_NUM_FORMS": "1000",
            "rules-0-id": str(rule.pk),
            "rules-0-name": "Tampered rule",
            "rules-0-impact": "LIMITED",
            "rules-0-target": "PRIORITY",
            "rules-0-outcome_code": "LOW",
            "scenarios-TOTAL_FORMS": "0",
            "scenarios-INITIAL_FORMS": "0",
            "scenarios-MIN_NUM_FORMS": "0",
            "scenarios-MAX_NUM_FORMS": "1000",
            "_save": "Save",
        },
    )
    assert response.status_code == 403
    policy.refresh_from_db()
    rule.refresh_from_db()
    assert (policy.name, policy.version, policy.status) == ("Approved", 1, "ACTIVE")
    assert (rule.name, rule.impact, rule.outcome_code) == (
        "Impact",
        "SIGNIFICANT",
        "HIGH",
    )


def test_admin_can_check_examples_without_activating_a_policy(
    admin_client: Client,
) -> None:
    """The example check reports a mismatch while leaving the draft unchanged."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    TriagePolicyRule.objects.create(
        policy=policy,
        name="Impact",
        impact="SIGNIFICANT",
        target="PRIORITY",
        outcome_code="HIGH",
    )
    TriagePolicyScenario.objects.create(
        policy=policy,
        name="Needs attention",
        impact="SIGNIFICANT",
        priority_state="determined",
        priority_code="LOW",
        urgency_state="ambiguous",
    )
    response = admin_client.post(
        reverse("admin:intake_triagepolicy_changelist"),
        {"action": "check_scenarios", "_selected_action": str(policy.pk)},
        follow=True,
    )
    assert b"Needs attention" in response.content
    policy.refresh_from_db()
    assert policy.status == "DRAFT"


def test_admin_can_view_shadow_counts_without_approving_automation(
    admin_client: Client,
) -> None:
    """Summary makes abstentions and the reviewed sample explicit."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    submission = ReportSubmission.objects.create(
        description="One", updates_requested=False
    )
    TriageAttempt.objects.create(
        submission=submission,
        stage="RULES",
        decision="PROPOSED",
        policy_version="1",
        field_outcomes={"priority": {"state": "ambiguous", "value": None}},
    )
    response = admin_client.post(
        reverse("admin:intake_triagepolicy_changelist"),
        {"action": "summarize_shadow", "_selected_action": str(policy.pk)},
        follow=True,
    )
    assert b"reports with proposals: 1" in response.content
    assert b"1 ambiguous" in response.content
    assert b"accepted reports only" in response.content
    policy.refresh_from_db()
    assert policy.status == "DRAFT"


def test_activation_requires_authorized_employee_and_explicit_confirmation(
    client: Client, make_employee: Callable[..., Employee]
) -> None:
    """Only an employee with activation permission can approve the draft."""
    policy = TriagePolicy.objects.create(version=1, name="Draft")
    TriagePolicyRule.objects.create(
        policy=policy,
        name="Impact",
        impact="SIGNIFICANT",
        target="PRIORITY",
        outcome_code="HIGH",
    )
    TriagePolicyScenario.objects.create(
        policy=policy,
        name="Example",
        impact="SIGNIFICANT",
        priority_state="determined",
        priority_code="HIGH",
        urgency_state="ambiguous",
    )
    employee = make_employee()
    employee.user.is_staff = True
    employee.user.save(update_fields=("is_staff",))
    employee.user.user_permissions.add(
        Permission.objects.get(codename="view_triagepolicy")
    )
    client.force_login(employee.user)
    url = reverse("admin:intake_triagepolicy_activate", args=[policy.pk])
    assert client.get(url).status_code == 403
    employee.user.user_permissions.add(
        Permission.objects.get(codename="activate_triagepolicy")
    )
    client.force_login(employee.user)
    response = client.get(url)
    assert response.status_code == 200
    assert b"Example: passed" in response.content
    assert client.post(url, {}).status_code == 200
    policy.refresh_from_db()
    assert policy.status == "DRAFT"
    assert client.post(url, {"confirmed": "on"}).status_code == 302
    policy.refresh_from_db()
    assert policy.status == "ACTIVE"
    assert policy.activated_by == employee
