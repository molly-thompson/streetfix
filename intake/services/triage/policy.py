"""Approval and activation of versioned triage policies."""

from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.utils import timezone

from employees.organisation_models import Employee
from intake.models import TriagePolicy
from intake.services.triage.scenarios import evaluate_scenarios
from intake.services.triage.taxonomy import snapshot_taxonomy


def activate_policy(policy_id: int, *, approver: Employee) -> None:
    """Activate a draft only after authorized review and passing examples.

    Activation enables proposals, not automatic decisions.
    """
    if approver.pk is None or not approver.user.has_perm(
        "intake.activate_triagepolicy"
    ):
        raise ValidationError("An authorized policy approver is required.")
    try:
        with transaction.atomic():
            policies = list(
                TriagePolicy.objects.select_for_update()
                .filter(
                    models.Q(pk=policy_id) | models.Q(status=TriagePolicy.Status.ACTIVE)
                )
                .order_by("pk")
            )
            draft = next(
                (policy for policy in policies if policy.pk == policy_id), None
            )
            if draft is None:
                raise ValidationError("The policy does not exist.")
            if draft.status != TriagePolicy.Status.DRAFT:
                raise ValidationError("Only a draft policy can be activated.")
            taxonomy = snapshot_taxonomy(lock=True)
            draft.full_clean()
            results = evaluate_scenarios(draft)
            if any(not result.passed for result in results):
                raise ValidationError(
                    "All policy examples must pass before activation."
                )
            for previous in policies:
                if previous.status == TriagePolicy.Status.ACTIVE:
                    previous.status = TriagePolicy.Status.RETIRED
                    models.Model.save(previous, update_fields=("status",))
            draft.status = TriagePolicy.Status.ACTIVE
            draft.taxonomy_snapshot = taxonomy
            draft.activated_at = timezone.now()
            draft.activated_by = approver
            models.Model.save(
                draft,
                update_fields=(
                    "status",
                    "taxonomy_snapshot",
                    "activated_at",
                    "activated_by",
                ),
            )
    except IntegrityError as exc:
        raise ValidationError(
            "Another policy was activated concurrently; retry."
        ) from exc
