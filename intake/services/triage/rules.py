"""Evaluate bounded policy rules without finalizing intake decisions."""

from collections.abc import Iterable
from enum import Enum

from intake.models import TriagePolicyRule
from intake.services.triage.results import Evidence, FieldOutcome, OutcomeState


class Match(Enum):
    """A rule may match, fail to match, or require missing evidence."""

    YES = 1
    NO = 2
    UNKNOWN = 3


def _match(rule: TriagePolicyRule, evidence: Evidence) -> Match:
    """Match all configured conditions without treating unknown as false."""
    pairs = (
        (rule.issue_type_id, evidence.issue_type_id),
        (rule.impact or None, evidence.impact),
        (rule.time_sensitivity or None, evidence.time_sensitivity),
        (rule.sensitive_content or None, evidence.sensitive_content),
    )
    unknown = False
    for required, actual in pairs:
        if required is None:
            continue
        if actual is None or actual == "UNKNOWN":
            unknown = True
        elif actual != required:
            return Match.NO
    return Match.UNKNOWN if unknown else Match.YES


def evaluate_field(
    rules: Iterable[TriagePolicyRule],
    *,
    target: str,
    evidence: Evidence,
) -> FieldOutcome:
    """Propose an outcome only when the matching rule set is unambiguous."""
    matched: list[TriagePolicyRule] = []
    uncertain = False
    for rule in rules:
        if rule.target != target:
            continue
        match = _match(rule, evidence)
        if match == Match.YES:
            matched.append(rule)
        elif match == Match.UNKNOWN:
            uncertain = True

    ids = tuple(sorted(rule.pk for rule in matched if rule.pk is not None))
    values = {rule.outcome_code for rule in matched}
    if len(values) > 1:
        return FieldOutcome(OutcomeState.CONFLICTING, matched_rule_ids=ids)
    if not values or uncertain:
        return FieldOutcome(OutcomeState.AMBIGUOUS, matched_rule_ids=ids)
    return FieldOutcome(OutcomeState.DETERMINED, values.pop(), ids)
