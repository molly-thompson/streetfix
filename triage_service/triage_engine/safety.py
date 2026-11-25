"""Independent, mandatory, negation-aware deterministic safety evaluator."""

from __future__ import annotations

import re
from dataclasses import dataclass

from triage_engine.config_models import OrganisationalTriageConfig
from triage_engine.schemas import (
    HazardSource,
    MatchedHazard,
    NegatedOrUncertainMention,
    SafetyAssessment,
)

# Clauses split on sentence/clause delimiters to avoid cross-sentence false negation
_CLAUSE_SPLIT_RE = re.compile(r"[.!?\n;]+")

# Explicit negation markers within a local prefix window before a hazard term
_NEGATION_RE = re.compile(
    r"\b(no|not|neither|nor|without|none|never|free of|away from|nowhere near|"
    r"confirmed no|checked and no|ruled out|absent)\b",
    re.IGNORECASE,
)

# Uncertainty / hedging markers indicating ambiguity rather than confirmed safety
_UNCERTAINTY_RE = re.compile(
    r"\b(possibly|maybe|might be|could be|not sure|unsure|unclear|unconfirmed|"
    r"suspected|hard to tell|cannot tell|think there is|looks like)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SystemSafetyRule:
    id: str
    label: str
    severity: str  # "critical" | "high" | "elevated"
    enforce_highest_priority: bool
    patterns: tuple[str, ...]
    recommended_action: str


# Non-negotiable system-level safeguards enforced consistently across ALL organisational profiles.
SYSTEM_SAFEGUARDS: tuple[SystemSafetyRule, ...] = (
    SystemSafetyRule(
        id="SYS_ELECTRICAL_WATER_HAZARD",
        label="Electrical shock or water-near-electrics hazard",
        severity="critical",
        enforce_highest_priority=True,
        patterns=(
            r"\b(?:live|exposed|sparking|arcing|hanging|downed)\s+(?:wires?|cables?|power\s*lines?)\b",
            r"\b(?:electric(?:al)?\s*(?:shock|sparks?|arcing)|electrocution)\b",
            r"\b(?:water|leak(?:ing)?|flood(?:ing)?|dripping|puddle)\b.{0,80}\b(?:socket|outlet|wiring|fuse\s*box|breaker|switchboard|electrical|distribution\s*board)\b",
            r"\b(?:socket|outlet|wiring|fuse\s*box|breaker|switchboard|electrical)\b.{0,80}\b(?:water|leak(?:ing)?|flood(?:ing)?|dripping|wet)\b",
        ),
        recommended_action=(
            "Keep people clear of the wet/electrical area immediately, isolate power if safe for "
            "qualified personnel, and dispatch emergency electrical response."
        ),
    ),
    SystemSafetyRule(
        id="SYS_GAS_EXPLOSION_HAZARD",
        label="Suspected gas leak, fumes, or explosion hazard",
        severity="critical",
        enforce_highest_priority=True,
        patterns=(
            r"\b(?:gas\s+leak|smell\s+of\s+gas|strong\s+gas\s+smell|hissing\s+(?:gas|pipe)|carbon\s+monoxide\s+alarm)\b",
        ),
        recommended_action=(
            "Evacuate immediate vicinity, prohibit ignition sources, and escalate immediately to "
            "emergency gas/utility response."
        ),
    ),
    SystemSafetyRule(
        id="SYS_FIRE_STRUCTURAL_COLLAPSE",
        label="Active fire, smoke, or structural collapse risk",
        severity="critical",
        enforce_highest_priority=True,
        patterns=(
            r"\b(?:on\s+fire|active\s+flames?|smoke\s+pouring|burning\s+smell\s+from\s+(?:panel|ceiling|pole))\b",
            r"\b(?:collaps(?:ing|ed)|cave[- ]in|sinkhole|wall\s+bulging|ceiling\s+(?:sagging|collapsing|caving))\b",
            r"\b(?:unguarded|open)\s+(?:deep\s+)?(?:excavation|trench|pit)\b",
        ),
        recommended_action=(
            "Establish immediate physical cordon/exclusion zone and alert emergency structural or fire response."
        ),
    ),
    SystemSafetyRule(
        id="SYS_TRAFFIC_LIFE_SAFETY",
        label="Severe highway/pedestrian life-safety obstruction",
        severity="high",
        enforce_highest_priority=False,
        patterns=(
            r"\b(?:traffic\s+(?:lights?|signals?)\s+(?:all\s+out|blackout|dead|failed))\b",
            r"\b(?:missing|open|uncovered)\s+(?:manhole|drain|inspection)\s+cover\b",
            r"\b(?:fallen\s+tree|debris)\s+(?:blocking|across)\s+(?:the\s+)?(?:road|carriageway|lane|highway)\b",
        ),
        recommended_action=(
            "Deploy urgent traffic management / temporary barrier to protect road users and pedestrians."
        ),
    ),
    SystemSafetyRule(
        id="SYS_SHARP_BIO_HAZARD",
        label="Sharps, asbestos, or hazardous chemical spill",
        severity="high",
        enforce_highest_priority=False,
        patterns=(
            r"\b(?:hypodermic\s+needles?|discarded\s+syringes?|sharps)\b",
            r"\b(?:asbestos|chemical\s+spill|toxic\s+drum|acid\s+leak)\b",
        ),
        recommended_action=(
            "Restrict public access and assign certified specialist hazmat/sharps containment team."
        ),
    ),
)

# Contradiction signal pairs: (positive_pattern, contradictory_negative_pattern, topic_label)
_CONTRADICTION_PAIRS: tuple[tuple[str, str, str], ...] = (
    (
        r"\b(?:flooding|water\s+pouring|heavy\s+leak|standing\s+water|submerged)\b",
        r"\b(?:completely\s+dry|totally\s+dry|bone\s+dry|no\s+water\s+visible|no\s+sign\s+of\s+water)\b",
        "Report contains conflicting claims regarding presence of water/flooding.",
    ),
    (
        r"\b(?:sparks?|sparking|live\s+wires?|on\s+fire|flames?)\b",
        r"\b(?:no\s+sparks?|not\s+sparking|no\s+live\s+wires?|no\s+fire|no\s+smoke)\b",
        "Report contains conflicting statements about active electrical sparking or fire.",
    ),
)


@dataclass
class DeterministicSafetyOutcome:
    assessment: SafetyAssessment
    enforced_min_priority_rank: int | None
    contradictions_detected: list[str]
    rules_triggered: list[str]
    requires_human_review: bool
    review_reasons: list[str]


def _classify_clause_match(clause: str, match_start: int) -> str:
    """
    Inspect the local prefix before a matched hazard inside the same clause.
    Returns 'positive', 'negated', or 'uncertain'.
    """
    prefix_window = clause[max(0, match_start - 55) : match_start]
    if _NEGATION_RE.search(prefix_window):
        return "negated"
    if _UNCERTAINTY_RE.search(prefix_window) or _UNCERTAINTY_RE.search(clause):
        return "uncertain"
    return "positive"


class SafetyEvaluator:
    """
    Independent deterministic safety evaluation pipeline.

    Runs prior to and overrides AI recommendations so high-risk hazards cannot be
    downgraded regardless of model confidence or organisational preferences.
    """

    def evaluate(
        self,
        text: str,
        org_config: OrganisationalTriageConfig,
    ) -> DeterministicSafetyOutcome:
        clauses = [c.strip() for c in _CLAUSE_SPLIT_RE.split(text) if c.strip()]

        matched_hazards: list[MatchedHazard] = []
        negated_or_uncertain: list[NegatedOrUncertainMention] = []
        warnings: list[str] = []
        actions: list[str] = []
        rules_triggered: list[str] = []
        review_reasons: list[str] = []
        enforced_min_rank: int | None = None
        seen_hazard_ids: set[str] = set()

        highest_rank = org_config.highest_priority().rank
        high_rank = min(highest_rank + 1, max(p.rank for p in org_config.priorities))

        # 1. Check contradictions first across full text
        contradictions: list[str] = []
        for pos_pat, neg_pat, label in _CONTRADICTION_PAIRS:
            pos_match = re.search(pos_pat, text, re.IGNORECASE)
            neg_match = re.search(neg_pat, text, re.IGNORECASE)
            if pos_match and neg_match:
                contradictions.append(label)
                negated_or_uncertain.append(
                    NegatedOrUncertainMention(
                        phrase=f"{pos_match.group(0)} ... {neg_match.group(0)}",
                        assessment="uncertain_or_contradictory",
                        explanation=label,
                    )
                )
                warnings.append(
                    f"Contradictory hazard details detected ({label}); human verification required."
                )
                rules_triggered.append("DET_SAFETY_CONTRADICTION")
                review_reasons.append(f"Contradictory safety information detected: {label}")

        # 2. Evaluate non-negotiable SYSTEM_SAFEGUARDS clause-by-clause
        for rule in SYSTEM_SAFEGUARDS:
            for clause in clauses:
                for pat in rule.patterns:
                    match = re.search(pat, clause, re.IGNORECASE)
                    if not match:
                        continue
                    classification = _classify_clause_match(clause, match.start())
                    if classification == "negated":
                        negated_or_uncertain.append(
                            NegatedOrUncertainMention(
                                phrase=clause,
                                assessment="negated",
                                explanation=(
                                    f"Hazard phrase '{match.group(0)}' appears negated in local context; "
                                    "not treated as confirmed active hazard."
                                ),
                            )
                        )
                        rules_triggered.append(f"NEGATED_CHECK:{rule.id}")
                        continue

                    if classification == "uncertain":
                        negated_or_uncertain.append(
                            NegatedOrUncertainMention(
                                phrase=clause,
                                assessment="uncertain_or_contradictory",
                                explanation=(
                                    f"Uncertain wording around potential hazard '{rule.label}'; "
                                    "requires human verification rather than assuming safety."
                                ),
                            )
                        )
                        warnings.append(
                            f"Uncertain safety reference ('{match.group(0)}') requires human review."
                        )
                        rules_triggered.append(f"UNCERTAIN_HAZARD:{rule.id}")
                        review_reasons.append(
                            f"Uncertain safety indicator for '{rule.label}' must be verified by an officer."
                        )
                        continue

                    # Confirmed positive match
                    if rule.id not in seen_hazard_ids:
                        seen_hazard_ids.add(rule.id)
                        matched_hazards.append(
                            MatchedHazard(
                                hazard_id=rule.id,
                                label=rule.label,
                                severity=rule.severity,  # type: ignore[arg-type]
                                source=HazardSource.SYSTEM_SAFEGUARD,
                                matched_text=match.group(0),
                                context_note=f"Matched clause: {clause[:160]}",
                            )
                        )
                        warnings.append(f"[SYSTEM SAFEGUARD] {rule.label} detected.")
                        actions.append(rule.recommended_action)
                        rules_triggered.append(rule.id)
                        review_reasons.append(f"System safety escalation triggered: {rule.label}.")

                        target_rank = highest_rank if rule.enforce_highest_priority else high_rank
                        enforced_min_rank = (
                            target_rank if enforced_min_rank is None else min(enforced_min_rank, target_rank)
                        )

        # 3. Evaluate organisation-configured safety_criteria (additive only)
        for criterion in org_config.safety_criteria:
            min_priority = org_config.priority_by_id(criterion.minimum_priority_id)
            for clause in clauses:
                for pat in criterion.patterns:
                    match = re.search(pat, clause, re.IGNORECASE)
                    if not match:
                        continue
                    classification = _classify_clause_match(clause, match.start())
                    if classification == "negated":
                        negated_or_uncertain.append(
                            NegatedOrUncertainMention(
                                phrase=clause,
                                assessment="negated",
                                explanation=f"Org criterion '{criterion.id}' appears negated in clause.",
                            )
                        )
                        continue
                    if classification == "uncertain":
                        negated_or_uncertain.append(
                            NegatedOrUncertainMention(
                                phrase=clause,
                                assessment="uncertain_or_contradictory",
                                explanation=f"Uncertain wording around org safety criterion '{criterion.label}'.",
                            )
                        )
                        review_reasons.append(
                            f"Uncertain match for organisational safety criterion '{criterion.label}'."
                        )
                        continue

                    if criterion.id not in seen_hazard_ids:
                        seen_hazard_ids.add(criterion.id)
                        matched_hazards.append(
                            MatchedHazard(
                                hazard_id=criterion.id,
                                label=criterion.label,
                                severity=criterion.severity,
                                source=HazardSource.ORG_POLICY,
                                matched_text=match.group(0),
                                context_note=f"Matched clause: {clause[:160]}",
                            )
                        )
                        warnings.append(f"[ORG POLICY] {criterion.label} detected.")
                        actions.append(criterion.recommended_action)
                        rules_triggered.append(f"ORG_SAFETY:{criterion.id}")
                        if criterion.require_human_review:
                            review_reasons.append(f"Organisational safety policy triggered: {criterion.label}.")
                        if min_priority is not None:
                            enforced_min_rank = (
                                min_priority.rank
                                if enforced_min_rank is None
                                else min(enforced_min_rank, min_priority.rank)
                            )

        escalation_triggered = len(matched_hazards) > 0
        min_priority_label = None
        if enforced_min_rank is not None:
            matching_p = next((p for p in org_config.priorities if p.rank == enforced_min_rank), None)
            if matching_p:
                min_priority_label = f"{matching_p.id} ({matching_p.name})"

        requires_review = escalation_triggered or len(review_reasons) > 0

        # Deduplicate actions/warnings/reasons preserving order
        dedup_warnings = list(dict.fromkeys(warnings))
        dedup_actions = list(dict.fromkeys(actions))
        dedup_reasons = list(dict.fromkeys(review_reasons))
        dedup_rules = list(dict.fromkeys(rules_triggered))

        assessment = SafetyAssessment(
            escalation_triggered=escalation_triggered,
            minimum_priority_enforced=min_priority_label,
            matched_hazards=matched_hazards,
            negated_or_uncertain_mentions=negated_or_uncertain,
            safety_warnings=dedup_warnings,
            recommended_immediate_actions=dedup_actions,
        )

        return DeterministicSafetyOutcome(
            assessment=assessment,
            enforced_min_priority_rank=enforced_min_rank,
            contradictions_detected=contradictions,
            rules_triggered=dedup_rules,
            requires_human_review=requires_review,
            review_reasons=dedup_reasons,
        )
