"""Structured evidence and outcomes for deterministic triage."""

from dataclasses import dataclass
from enum import StrEnum


class OutcomeState(StrEnum):
    """Whether configured rules yield a unique result."""

    DETERMINED = "determined"
    AMBIGUOUS = "ambiguous"
    CONFLICTING = "conflicting"


@dataclass(frozen=True)
class Evidence:
    """Bounded evidence values; unknown inputs are represented by None."""

    issue_type_id: int | None = None
    impact: str | None = None
    time_sensitivity: str | None = None
    sensitive_content: str | None = None


@dataclass(frozen=True)
class FieldOutcome:
    """A proposed rule result; it is not itself an approved decision."""

    state: OutcomeState
    value: str | None = None
    matched_rule_ids: tuple[int, ...] = ()
