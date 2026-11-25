"""Verifiable evidence attribution and verbatim excerpt checking."""

from __future__ import annotations

import re

from triage_engine.schemas import (
    AITriageRawOutput,
    EvidenceAndReasoning,
    EvidenceExcerpt,
    InferredConclusion,
)

_WS_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WS_RE.sub(" ", text).strip().casefold()


def quote_exists_in_source(quote: str, source_corpus: str) -> bool:
    """Verify whether an excerpt exists verbatim (ignoring minor whitespace/case differences) in input."""
    cleaned_quote = _normalize(quote)
    if len(cleaned_quote) < 3:
        return False
    return cleaned_quote in _normalize(source_corpus)


def verify_and_build_evidence(
    raw_description: str,
    location_summary: str | None,
    context_notes: str | None,
    ai_output: AITriageRawOutput,
    deterministic_contradictions: list[str],
) -> tuple[EvidenceAndReasoning, bool]:
    """
    Build verifiable EvidenceAndReasoning separating reported facts, verbatim excerpts,
    and AI-inferred conclusions.

    Returns (EvidenceAndReasoning, has_unverified_or_contradictory_evidence).
    """
    source_parts = [raw_description]
    if location_summary:
        source_parts.append(location_summary)
    if context_notes:
        source_parts.append(context_notes)
    source_corpus = "\n".join(source_parts)

    verified_excerpts: list[EvidenceExcerpt] = []
    flags: list[str] = list(deterministic_contradictions)
    has_unverified = False

    for idx, item in enumerate(ai_output.evidence_excerpts, start=1):
        excerpt_id = f"EX-{idx:02d}"
        is_verified = quote_exists_in_source(item.quote, source_corpus)
        note: str | None = None
        if not is_verified:
            has_unverified = True
            note = (
                "Unverified quote: text did not match the submitted report verbatim and cannot be "
                "treated as an established reporter statement."
            )
            flags.append(
                f"Unverified evidence excerpt '{excerpt_id}' did not match submitted input verbatim."
            )
        verified_excerpts.append(
            EvidenceExcerpt(
                excerpt_id=excerpt_id,
                quote=item.quote,
                verified_in_source=is_verified,
                verification_note=note,
                supports_recommendations=item.supports,
            )
        )

    for item in ai_output.contradictions_or_ambiguities:
        if item not in flags:
            flags.append(item)

    inferred_items = [
        InferredConclusion(
            conclusion=inf.conclusion,
            basis=inf.basis,
            uncertainty_note=inf.uncertainty_note,
            explicitly_inferred=True,
        )
        for inf in ai_output.inferred_conclusions
    ]

    # Deduplicate flags preserving order
    dedup_flags = list(dict.fromkeys(flags))
    has_issues = has_unverified or len(dedup_flags) > 0

    evidence = EvidenceAndReasoning(
        reported_facts=ai_output.reported_facts,
        evidence_excerpts=verified_excerpts,
        inferred_conclusions=inferred_items,
        unsupported_or_contradictory_flags=dedup_flags,
        reasoning_summary=ai_output.reasoning_summary,
    )
    return evidence, has_issues
