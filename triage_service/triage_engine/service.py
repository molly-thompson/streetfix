"""Framework-independent core triage orchestration and cross-organisation comparison service."""

from __future__ import annotations

import logging
import re
import time
import uuid

from triage_engine.config_loader import (
    ConfigRegistry,
    EffectiveTriagePolicy,
    apply_safe_override,
)
from triage_engine.config_models import OrganisationalTriageConfig, PriorityLevelConfig
from triage_engine.evidence import verify_and_build_evidence
from triage_engine.providers.base import ProviderError, TriageAIProvider
from triage_engine.safety import DeterministicSafetyOutcome, SafetyEvaluator
from triage_engine.schemas import (
    AITriageRawOutput,
    CategoryCandidate,
    CategoryRecommendation,
    DecisionUncertaintyAssessment,
    DecisionUncertaintyLevel,
    EvidenceAndReasoning,
    EvidenceQualityAssessment,
    EvidenceQualityLevel,
    HazardSource,
    HumanReviewAssessment,
    MatchedHazard,
    MaterialImpact,
    MissingInformationItem,
    ModelSelfAssessment,
    PriorityRecommendation,
    ProfileComparisonDiff,
    ProviderMetadata,
    QualitativeConfidence,
    RoutingRecommendation,
    RoutingSource,
    TriageCompareRequest,
    TriageCompareResponse,
    TriageRequest,
    TriageResponse,
    TriageStatus,
    UncertaintyAssessment,
)

logger = logging.getLogger("triage_engine.service")


class TriageService:
    """
    Core decision-support triage engine decoupled from FastAPI and external databases.
    """

    def __init__(
        self,
        config_registry: ConfigRegistry,
        ai_provider: TriageAIProvider,
        safety_evaluator: SafetyEvaluator | None = None,
    ) -> None:
        self.config_registry = config_registry
        self.ai_provider = ai_provider
        self.safety_evaluator = safety_evaluator or SafetyEvaluator()

    def triage(self, request: TriageRequest) -> TriageResponse:
        start = time.monotonic()
        request_id = f"tr_{uuid.uuid4().hex[:12]}"
        org_config = self.config_registry.get(request.profile_id)
        policy = apply_safe_override(org_config, request.config_override)

        combined_text = self._combine_safety_text(request)
        safety_outcome = self.safety_evaluator.evaluate(combined_text, org_config)
        criterion_priority = self._evaluate_priority_criteria(combined_text, org_config)

        try:
            ai_output = self.ai_provider.analyze_report(request, policy)
        except ProviderError as exc:
            if not request.allow_degraded_on_ai_error:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.warning(
                    "triage_failed request_id=%s profile=%s error_code=%s elapsed_ms=%d",
                    request_id,
                    org_config.profile_id,
                    exc.error_code,
                    elapsed_ms,
                )
                raise

            response = self._build_degraded_response(
                request_id=request_id,
                request=request,
                policy=policy,
                safety_outcome=safety_outcome,
                criterion_priority=criterion_priority,
                provider_error=exc,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.info(
                "triage_completed request_id=%s profile=%s status=%s safety_escalated=%s review=%s elapsed_ms=%d",
                request_id,
                org_config.profile_id,
                response.status.value,
                response.safety_assessment.escalation_triggered,
                response.human_review.required,
                elapsed_ms,
            )
            return response

        response = self._reconcile_completed_response(
            request_id=request_id,
            request=request,
            policy=policy,
            safety_outcome=safety_outcome,
            criterion_priority=criterion_priority,
            ai_output=ai_output,
        )
        elapsed_ms = int((time.monotonic() - start) * 1000)
        logger.info(
            "triage_completed request_id=%s profile=%s status=%s safety_escalated=%s review=%s elapsed_ms=%d",
            request_id,
            org_config.profile_id,
            response.status.value,
            response.safety_assessment.escalation_triggered,
            response.human_review.required,
            elapsed_ms,
        )
        return response

    def compare(self, request: TriageCompareRequest) -> TriageCompareResponse:
        """
        Evaluate an identical report payload across multiple organisational profiles.
        """
        comparison_id = f"cmp_{uuid.uuid4().hex[:12]}"
        results_by_profile: dict[str, TriageResponse] = {}

        # Validate all profile_ids upfront before invoking provider
        for profile_id in request.profile_ids:
            self.config_registry.get(profile_id)

        for profile_id in request.profile_ids:
            single_req = TriageRequest(
                description=request.report.description,
                location=request.report.location,
                context=request.report.context,
                metadata=dict(request.report.metadata),
                profile_id=profile_id,
                allow_degraded_on_ai_error=request.allow_degraded_on_ai_error,
            )
            results_by_profile[profile_id] = self.triage(single_req)

        # Verify mandatory system-level safety safeguards behave consistently across profiles
        sys_hazard_sets = [
            {
                h.hazard_id
                for h in res.safety_assessment.matched_hazards
                if h.source == HazardSource.SYSTEM_SAFEGUARD
            }
            for res in results_by_profile.values()
        ]
        safety_consistency_verified = all(s == sys_hazard_sets[0] for s in sys_hazard_sets)

        comparison_diffs = self._build_comparison_diffs(results_by_profile)
        policy_explanation = self._build_policy_explanation(
            results_by_profile, comparison_diffs, safety_consistency_verified
        )

        preview = request.report.description[:140] + (
            "..." if len(request.report.description) > 140 else ""
        )
        loc_summary = request.report.location.as_summary_text() if request.report.location else None

        return TriageCompareResponse(
            comparison_id=comparison_id,
            shared_description_preview=preview,
            shared_location_summary=loc_summary or None,
            results_by_profile=results_by_profile,
            safety_consistency_verified=safety_consistency_verified,
            comparison_diffs=comparison_diffs,
            policy_explanation=policy_explanation,
        )

    @staticmethod
    def _combine_safety_text(request: TriageRequest) -> str:
        parts = [request.description]
        if request.location:
            summary = request.location.as_summary_text()
            if summary:
                parts.append(summary)
        if request.context and request.context.additional_notes:
            parts.append(request.context.additional_notes)
        return "\n".join(parts)

    @staticmethod
    def _evaluate_priority_criteria(
        text: str, org_config: OrganisationalTriageConfig
    ) -> PriorityLevelConfig | None:
        best: PriorityLevelConfig | None = None
        for criterion in org_config.priority_criteria:
            target = org_config.priority_by_id(criterion.priority_id)
            if not target:
                continue
            for pat in criterion.signal_patterns:
                if re.search(pat, text, re.IGNORECASE):
                    if best is None or target.rank < best.rank:
                        best = target
                    break
        return best

    def _build_degraded_response(
        self,
        request_id: str,
        request: TriageRequest,
        policy: EffectiveTriagePolicy,
        safety_outcome: DeterministicSafetyOutcome,
        criterion_priority: PriorityLevelConfig | None,
        provider_error: ProviderError,
    ) -> TriageResponse:
        cfg = policy.org_config
        rules_triggered = list(safety_outcome.rules_triggered) + ["DEGRADED_AI_UNAVAILABLE"]

        # Priority strictly from deterministic safety / policy criteria, never fabricated AI priority
        enforced_rank = safety_outcome.enforced_min_priority_rank
        if criterion_priority is not None:
            enforced_rank = (
                criterion_priority.rank
                if enforced_rank is None
                else min(enforced_rank, criterion_priority.rank)
            )

        if enforced_rank is not None:
            matched_p = next((p for p in cfg.priorities if p.rank == enforced_rank), None)
            priority_rec = PriorityRecommendation(
                priority_id=matched_p.id if matched_p else None,
                priority_name=matched_p.name if matched_p else None,
                rank=matched_p.rank if matched_p else None,
                escalated_by_safety=safety_outcome.assessment.escalation_triggered,
                rationale=(
                    "Priority floor assigned strictly by deterministic safety/policy rules while "
                    "AI processing was unavailable."
                ),
            )
        else:
            priority_rec = PriorityRecommendation(
                priority_id=None,
                priority_name=None,
                rank=None,
                escalated_by_safety=False,
                rationale="Priority withheld: AI assessment unavailable and no deterministic priority rule matched.",
            )

        fallback_team = cfg.team_by_id(cfg.default_fallback_team_id) if cfg.default_fallback_team_id else None
        routing_rec = RoutingRecommendation(
            team_id=fallback_team.id if fallback_team else None,
            team_name=fallback_team.name if fallback_team else None,
            routing_source=RoutingSource.UNASSIGNED_FOR_REVIEW,
            rationale=(
                "Routed to fallback triage desk for manual assessment because AI classification was unavailable."
            ),
        )

        missing_items = self._build_deterministic_missing_info(request, policy, existing_fields=set())

        review_reasons = [
            "AI assessment could not be obtained (degraded deterministic-only mode); manual triage is required."
        ] + safety_outcome.review_reasons

        return TriageResponse(
            request_id=request_id,
            profile_used=cfg.profile_id,
            organisation_name=cfg.organisation_name,
            status=TriageStatus.DEGRADED,
            category_recommendation=CategoryRecommendation(
                abstained=True,
                abstention_reason=(
                    "Degraded mode: AI interpretation unavailable; no category inferred from deterministic rules alone."
                ),
            ),
            priority_recommendation=priority_rec,
            routing_recommendation=routing_rec,
            safety_assessment=safety_outcome.assessment,
            missing_information=missing_items,
            evidence_and_reasoning=EvidenceAndReasoning(
                reported_facts=[request.description],
                evidence_excerpts=[],
                inferred_conclusions=[],
                unsupported_or_contradictory_flags=safety_outcome.contradictions_detected,
                reasoning_summary=(
                    "Deterministic safety and completeness checks executed. Natural-language AI analysis "
                    f"was unavailable ({provider_error.error_code}); no AI conclusions were generated."
                ),
            ),
            uncertainty_assessment=UncertaintyAssessment(
                model_self_assessment=ModelSelfAssessment(
                    qualitative_level=QualitativeConfidence.INSUFFICIENT,
                    uncalibrated_estimate=None,
                ),
                evidence_quality=EvidenceQualityAssessment(
                    level=EvidenceQualityLevel.PARTIAL if request.location else EvidenceQualityLevel.INSUFFICIENT,
                    explanation="Not fully assessed because the AI provider was unavailable.",
                    missing_critical_context=request.location is None,
                ),
                decision_uncertainty=DecisionUncertaintyAssessment(
                    level=DecisionUncertaintyLevel.HIGH,
                    plausible_alternatives_exist=True,
                    explanation="Automated classification was not completed.",
                    ambiguities=["AI provider unavailable during evaluation."],
                ),
                abstained_dimensions=["category", "ai_reasoning"],
                limitations=[
                    "Degraded response: reflects deterministic safety/policy rules only, not AI language analysis."
                ],
            ),
            human_review=HumanReviewAssessment(
                required=True,
                reasons=list(dict.fromkeys(review_reasons)),
                recommended_reviewer_actions=[
                    "Perform manual category, priority, and routing assessment.",
                    "Confirm any deterministic safety escalations immediately.",
                ],
            ),
            provider_metadata=ProviderMetadata(
                provider_name=self.ai_provider.provider_name,
                model_name=policy.effective_model_name,
                ai_assessment_obtained=False,
                error_code=provider_error.error_code,
                error_detail=provider_error.public_message,
            ),
            deterministic_rules_triggered=rules_triggered,
            warnings=[
                f"Degraded mode active ({provider_error.error_code}): {provider_error.public_message}"
            ]
            + safety_outcome.assessment.safety_warnings,
        )

    def _reconcile_completed_response(
        self,
        request_id: str,
        request: TriageRequest,
        policy: EffectiveTriagePolicy,
        safety_outcome: DeterministicSafetyOutcome,
        criterion_priority: PriorityLevelConfig | None,
        ai_output: AITriageRawOutput,
    ) -> TriageResponse:
        cfg = policy.org_config
        warnings: list[str] = list(safety_outcome.assessment.safety_warnings)
        rules_triggered = list(safety_outcome.rules_triggered)
        review_reasons = list(safety_outcome.review_reasons)
        abstained_dimensions: list[str] = []

        # 1. Verify evidence excerpts verbatim against source input
        location_summary = request.location.as_summary_text() if request.location else None
        context_notes = request.context.additional_notes if request.context else None
        evidence_obj, has_evidence_issues = verify_and_build_evidence(
            raw_description=request.description,
            location_summary=location_summary or None,
            context_notes=context_notes,
            ai_output=ai_output,
            deterministic_contradictions=safety_outcome.contradictions_detected,
        )
        verified_ids = [ex.excerpt_id for ex in evidence_obj.evidence_excerpts if ex.verified_in_source]

        if has_evidence_issues:
            rules_triggered.append("EVIDENCE_VERIFICATION_FLAG")
            review_reasons.append(
                "Unverified evidence quote or contradictory/ambiguous details detected; human review required."
            )
            warnings.extend(evidence_obj.unsupported_or_contradictory_flags)

        # 2. Merge AI-flagged safety concerns with deterministic safety (AI cannot remove deterministic hazards)
        safety_assessment = safety_outcome.assessment.model_copy(deep=True)
        for flag in ai_output.ai_safety_flags:
            already_covered = any(
                flag.label.lower() in h.label.lower() or h.label.lower() in flag.label.lower()
                for h in safety_assessment.matched_hazards
            )
            if not already_covered:
                safety_assessment.matched_hazards.append(
                    MatchedHazard(
                        hazard_id=f"AI_FLAG_{len(safety_assessment.matched_hazards) + 1}",
                        label=flag.label,
                        severity=flag.severity,
                        source=HazardSource.AI_FLAGGED,
                        matched_text=flag.matched_text,
                        context_note=flag.rationale,
                    )
                )
                safety_assessment.escalation_triggered = True
                safety_assessment.safety_warnings.append(f"[AI SAFETY FLAG] {flag.label}: {flag.rationale}")
                review_reasons.append(f"AI safety concern flagged: {flag.label}.")

        # 3. Validate Category & Abstention logic
        matched_category = (
            cfg.category_by_id(ai_output.suggested_category_id)
            if ai_output.suggested_category_id
            else None
        )
        should_abstain_category = (
            ai_output.abstain_category
            or matched_category is None
            or ai_output.model_uncalibrated_estimate < cfg.confidence_thresholds.abstention_threshold
            or ai_output.evidence_quality == EvidenceQualityLevel.INSUFFICIENT
        )

        abstention_reason = ai_output.abstention_reason
        if not ai_output.abstain_category and ai_output.suggested_category_id and matched_category is None:
            should_abstain_category = True
            abstention_reason = (
                f"AI suggested unrecognised category '{ai_output.suggested_category_id}'; abstained safely."
            )
            warnings.append(abstention_reason)
        elif (
            should_abstain_category
            and not abstention_reason
            and ai_output.model_uncalibrated_estimate < cfg.confidence_thresholds.abstention_threshold
        ):
            abstention_reason = (
                f"Model self-estimate ({ai_output.model_uncalibrated_estimate:.2f}) fell below configured "
                f"abstention threshold ({cfg.confidence_thresholds.abstention_threshold:.2f})."
            )
        elif should_abstain_category and not abstention_reason:
            abstention_reason = "Available evidence is insufficient for reliable category assignment."

        alt_candidates: list[CategoryCandidate] = []
        for alt in ai_output.alternative_category_ids:
            alt_cfg = cfg.category_by_id(alt.category_id)
            if alt_cfg and (matched_category is None or alt_cfg.id != matched_category.id):
                alt_candidates.append(
                    CategoryCandidate(
                        category_id=alt_cfg.id,
                        category_name=alt_cfg.name,
                        plausibility_note=alt.plausibility_note,
                    )
                )

        if should_abstain_category:
            abstained_dimensions.append("category")
            rules_triggered.append("ABSTENTION_GATE")
            review_reasons.append(abstention_reason or "Engine abstained from category assignment.")
            category_rec = CategoryRecommendation(
                primary_category_id=None,
                primary_category_name=None,
                alternative_candidates=alt_candidates,
                abstained=True,
                abstention_reason=abstention_reason,
                supporting_evidence_ids=verified_ids,
            )
        else:
            assert matched_category is not None
            category_rec = CategoryRecommendation(
                primary_category_id=matched_category.id,
                primary_category_name=matched_category.name,
                alternative_candidates=alt_candidates,
                abstained=False,
                supporting_evidence_ids=verified_ids,
            )
            if matched_category.always_require_human_review:
                review_reasons.append(
                    f"Category '{matched_category.name}' is configured to always require human review."
                )

        # 4. Priority Resolution (Deterministic Safety & Priority Criteria cannot be downgraded by AI)
        ai_priority = (
            cfg.priority_by_id(ai_output.suggested_priority_id)
            if ai_output.suggested_priority_id
            else None
        )
        enforced_rank = safety_outcome.enforced_min_priority_rank
        if criterion_priority is not None:
            enforced_rank = (
                criterion_priority.rank
                if enforced_rank is None
                else min(enforced_rank, criterion_priority.rank)
            )
            rules_triggered.append("ORG_PRIORITY_CRITERION")

        escalated_by_safety = False
        final_priority: PriorityLevelConfig | None = ai_priority
        priority_rationale = ai_output.priority_rationale

        if enforced_rank is not None:
            floor_priority = next((p for p in cfg.priorities if p.rank == enforced_rank), None)
            if floor_priority and (ai_priority is None or ai_priority.rank > floor_priority.rank):
                final_priority = floor_priority
                if safety_outcome.enforced_min_priority_rank == enforced_rank:
                    escalated_by_safety = True
                    rules_triggered.append("SAFETY_PRIORITY_OVERRIDE")
                    priority_rationale = (
                        f"Escalated to {floor_priority.id} ({floor_priority.name}) by deterministic safety "
                        f"rules regardless of AI priority assessment. {ai_output.priority_rationale}"
                    )
                else:
                    priority_rationale = (
                        f"Elevated to {floor_priority.id} ({floor_priority.name}) by configured priority "
                        f"criteria. {ai_output.priority_rationale}"
                    )
            elif safety_outcome.enforced_min_priority_rank is not None:
                escalated_by_safety = True

        if final_priority is None and should_abstain_category:
            abstained_dimensions.append("priority")
            priority_rec = PriorityRecommendation(
                priority_id=None,
                priority_name=None,
                rank=None,
                escalated_by_safety=False,
                rationale="Priority withheld pending missing information and human triage.",
                supporting_evidence_ids=verified_ids,
            )
        else:
            if final_priority is None:
                # Safe conservative mid-priority fallback if AI returned invalid priority ID
                sorted_p = sorted(cfg.priorities, key=lambda p: p.rank)
                final_priority = sorted_p[min(1, len(sorted_p) - 1)]
                review_reasons.append("AI suggested an invalid priority ID; conservative fallback applied.")
            priority_rec = PriorityRecommendation(
                priority_id=final_priority.id,
                priority_name=final_priority.name,
                rank=final_priority.rank,
                escalated_by_safety=escalated_by_safety,
                rationale=priority_rationale,
                supporting_evidence_ids=verified_ids,
            )
            if final_priority.id in cfg.human_review_rules.always_review_priority_ids:
                review_reasons.append(
                    f"Priority '{final_priority.id} ({final_priority.name})' requires mandatory human review."
                )

        # 5. Deterministic Routing Resolution
        routing_rec = self._resolve_routing(
            cfg=cfg,
            category_id=category_rec.primary_category_id,
            ai_team_id=ai_output.suggested_team_id,
            ai_rationale=ai_output.routing_rationale,
            abstained=should_abstain_category,
        )

        # 6. Missing Information Consolidation
        missing_items = [
            MissingInformationItem(
                field=item.field,
                question=item.question,
                reason=item.reason,
                material_impact=item.material_impact,
            )
            for item in ai_output.missing_information
        ]
        existing_fields = {m.field.lower() for m in missing_items}
        missing_items.extend(
            self._build_deterministic_missing_info(
                request,
                policy,
                existing_fields=existing_fields,
                requires_location=(matched_category.requires_location if matched_category else True),
            )
        )

        # 7. Human Review Gatekeeping
        if policy.force_human_review:
            review_reasons.append("Request override explicitly enforced mandatory human review.")
            rules_triggered.append("OVERRIDE_FORCE_REVIEW")

        if ai_output.model_uncalibrated_estimate < policy.effective_human_review_threshold:
            review_reasons.append(
                f"Uncalibrated model estimate ({ai_output.model_uncalibrated_estimate:.2f}) is below "
                f"human-review threshold ({policy.effective_human_review_threshold:.2f})."
            )
            rules_triggered.append("CONFIDENCE_THRESHOLD_REVIEW")

        if (
            cfg.human_review_rules.review_on_multi_category_ambiguity
            and (len(alt_candidates) > 0 or ai_output.decision_uncertainty == DecisionUncertaintyLevel.HIGH)
        ):
            review_reasons.append(
                "Plausible alternative categories or high decision uncertainty detected."
            )
            rules_triggered.append("AMBIGUITY_REVIEW_GATE")

        if cfg.human_review_rules.review_on_missing_critical_info and any(
            m.material_impact == MaterialImpact.HIGH for m in missing_items
        ):
            review_reasons.append("High-impact missing information could materially alter triage outcome.")

        if ai_output.recommend_human_review:
            review_reasons.extend(ai_output.human_review_reasons or ["AI flagged case for officer verification."])

        dedup_review_reasons = list(dict.fromkeys(review_reasons))
        human_review_required = len(dedup_review_reasons) > 0 or safety_assessment.escalation_triggered

        reviewer_actions: list[str] = []
        if safety_assessment.escalation_triggered:
            reviewer_actions.append("Verify immediate safety escalation and confirm emergency dispatch.")
        if should_abstain_category:
            reviewer_actions.append("Request missing details from reporter or manually assign category.")
        if has_evidence_issues:
            reviewer_actions.append("Check contradictory/unverified details against the original report.")
        if not reviewer_actions and human_review_required:
            reviewer_actions.append("Confirm recommended category, priority, and operational team before dispatch.")

        status = TriageStatus.ABSTAINED if should_abstain_category else TriageStatus.COMPLETED

        limitations = [
            "Confidence indicator reflects an uncalibrated model self-estimate, not proven real-world accuracy.",
            "AI-inferred conclusions are separated from reported facts and require officer verification.",
        ]
        if policy.override_applied:
            limitations.append("Evaluated with an allowlisted, non-weakening request contextual override.")

        return TriageResponse(
            request_id=request_id,
            profile_used=cfg.profile_id,
            organisation_name=cfg.organisation_name,
            status=status,
            category_recommendation=category_rec,
            priority_recommendation=priority_rec,
            routing_recommendation=routing_rec,
            safety_assessment=safety_assessment,
            missing_information=missing_items,
            evidence_and_reasoning=evidence_obj,
            uncertainty_assessment=UncertaintyAssessment(
                model_self_assessment=ModelSelfAssessment(
                    qualitative_level=ai_output.model_qualitative_confidence,
                    uncalibrated_estimate=ai_output.model_uncalibrated_estimate,
                ),
                evidence_quality=EvidenceQualityAssessment(
                    level=ai_output.evidence_quality,
                    explanation=ai_output.evidence_quality_explanation,
                    missing_critical_context=any(m.material_impact == MaterialImpact.HIGH for m in missing_items),
                ),
                decision_uncertainty=DecisionUncertaintyAssessment(
                    level=ai_output.decision_uncertainty,
                    plausible_alternatives_exist=len(alt_candidates) > 0,
                    explanation=ai_output.decision_uncertainty_explanation,
                    ambiguities=ai_output.contradictions_or_ambiguities,
                ),
                abstained_dimensions=abstained_dimensions,
                limitations=limitations,
            ),
            human_review=HumanReviewAssessment(
                required=human_review_required,
                reasons=dedup_review_reasons,
                recommended_reviewer_actions=reviewer_actions,
            ),
            provider_metadata=ProviderMetadata(
                provider_name=self.ai_provider.provider_name,
                model_name=policy.effective_model_name,
                ai_assessment_obtained=True,
            ),
            deterministic_rules_triggered=list(dict.fromkeys(rules_triggered)),
            warnings=list(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _resolve_routing(
        cfg: OrganisationalTriageConfig,
        category_id: str | None,
        ai_team_id: str | None,
        ai_rationale: str,
        abstained: bool,
    ) -> RoutingRecommendation:
        fallback_team = cfg.team_by_id(cfg.default_fallback_team_id) if cfg.default_fallback_team_id else None

        if abstained or category_id is None:
            return RoutingRecommendation(
                team_id=fallback_team.id if fallback_team else None,
                team_name=fallback_team.name if fallback_team else None,
                routing_source=RoutingSource.UNASSIGNED_FOR_REVIEW,
                rationale=(
                    "Category abstained; routed to triage fallback desk for human review."
                    if fallback_team
                    else "Category abstained; no team assigned until human triage."
                ),
            )

        rule = cfg.routing_for_category(category_id)
        if rule is not None:
            team = cfg.team_by_id(rule.team_id)
            if team is not None:
                return RoutingRecommendation(
                    team_id=team.id,
                    team_name=team.name,
                    routing_source=RoutingSource.CONFIGURED_RULE,
                    rationale=f"Assigned via configured routing rule for category '{category_id}'.",
                )

        if cfg.allow_ai_team_routing_when_unmapped and ai_team_id:
            ai_team = cfg.team_by_id(ai_team_id)
            if ai_team is not None:
                return RoutingRecommendation(
                    team_id=ai_team.id,
                    team_name=ai_team.name,
                    routing_source=RoutingSource.AI_ASSISTED,
                    rationale=ai_rationale,
                )

        return RoutingRecommendation(
            team_id=fallback_team.id if fallback_team else None,
            team_name=fallback_team.name if fallback_team else None,
            routing_source=RoutingSource.UNASSIGNED_FOR_REVIEW,
            rationale="No specific category rule matched; assigned to fallback desk.",
        )

    @staticmethod
    def _build_deterministic_missing_info(
        request: TriageRequest,
        policy: EffectiveTriagePolicy,
        existing_fields: set[str],
        requires_location: bool = True,
    ) -> list[MissingInformationItem]:
        items: list[MissingInformationItem] = []
        has_location = request.location is not None and bool(request.location.as_summary_text())
        if requires_location and not has_location and "location" not in existing_fields:
            items.append(
                MissingInformationItem(
                    field="location",
                    question="What is the exact street address, building, or landmark for this issue?",
                    reason="No structured or textual location was provided with the report.",
                    material_impact=MaterialImpact.HIGH,
                )
            )
        for idx, extra_prompt in enumerate(policy.additional_missing_info_prompts, start=1):
            field_name = f"custom_prompt_{idx}"
            if field_name not in existing_fields:
                items.append(
                    MissingInformationItem(
                        field=field_name,
                        question=extra_prompt,
                        reason="Requested via allowlisted operational evaluation override.",
                        material_impact=MaterialImpact.MEDIUM,
                    )
                )
        return items

    @staticmethod
    def _build_comparison_diffs(
        results_by_profile: dict[str, TriageResponse],
    ) -> list[ProfileComparisonDiff]:
        profiles = list(results_by_profile.keys())

        def make_diff(dimension: str, extractor, same_msg: str, diff_msg: str) -> ProfileComparisonDiff:
            vals = {pid: extractor(results_by_profile[pid]) for pid in profiles}
            differs = len(set(vals.values())) > 1
            return ProfileComparisonDiff(
                dimension=dimension,
                differs=differs,
                summary=diff_msg if differs else same_msg,
                values_by_profile=vals,
            )

        return [
            make_diff(
                "category",
                lambda r: (
                    "Abstained"
                    if r.category_recommendation.abstained
                    else f"{r.category_recommendation.primary_category_name} ({r.category_recommendation.primary_category_id})"
                ),
                "All profiles selected equivalent category labels.",
                "Profiles mapped the identical report to different organisational categories.",
            ),
            make_diff(
                "priority",
                lambda r: (
                    f"{r.priority_recommendation.priority_id} - {r.priority_recommendation.priority_name}"
                    if r.priority_recommendation.priority_id
                    else "Withheld"
                ),
                "All profiles assigned matching priority labels.",
                "Profiles assigned different priority tiers/targets based on their configured scales.",
            ),
            make_diff(
                "team",
                lambda r: (
                    f"{r.routing_recommendation.team_name} ({r.routing_recommendation.team_id})"
                    if r.routing_recommendation.team_id
                    else "Unassigned"
                ),
                "Profiles routed to the same team identifier.",
                "Profiles routed to different operational teams per their routing tables.",
            ),
            make_diff(
                "safety_assessment",
                lambda r: (
                    "Escalated ("
                    + ", ".join(
                        sorted(
                            h.hazard_id
                            for h in r.safety_assessment.matched_hazards
                            if h.source == HazardSource.SYSTEM_SAFEGUARD
                        )
                    )
                    + ")"
                    if r.safety_assessment.escalation_triggered
                    and any(
                        h.source == HazardSource.SYSTEM_SAFEGUARD
                        for h in r.safety_assessment.matched_hazards
                    )
                    else (
                        f"Escalated ({len(r.safety_assessment.matched_hazards)} org/AI hazard(s))"
                        if r.safety_assessment.escalation_triggered
                        else "No escalation"
                    )
                ),
                "Safety escalation posture remained consistent across all profiles.",
                "Safety escalation differed due to organisation-specific safety rules.",
            ),
            make_diff(
                "missing_information",
                lambda r: (
                    f"{len(r.missing_information)} item(s): "
                    + ", ".join(m.field for m in r.missing_information)
                    if r.missing_information
                    else "None flagged"
                ),
                "Profiles requested identical missing-information follow-ups.",
                "Profiles identified different missing-information questions.",
            ),
            make_diff(
                "confidence_and_uncertainty",
                lambda r: (
                    f"Model={r.uncertainty_assessment.model_self_assessment.qualitative_level.value}, "
                    f"Evidence={r.uncertainty_assessment.evidence_quality.level.value}, "
                    f"Decision={r.uncertainty_assessment.decision_uncertainty.level.value}"
                ),
                "Uncertainty dimensions aligned across profiles.",
                "Uncertainty or evidence-quality assessments differed across organisational policies.",
            ),
            make_diff(
                "human_review",
                lambda r: "Required" if r.human_review.required else "Not required",
                "Human review requirement is consistent across profiles.",
                "Human review thresholds/rules differed across profiles.",
            ),
        ]

    @staticmethod
    def _build_policy_explanation(
        results_by_profile: dict[str, TriageResponse],
        diffs: list[ProfileComparisonDiff],
        safety_consistency_verified: bool,
    ) -> str:
        divergent_dims = [d.dimension for d in diffs if d.differs]
        escalated_any = any(r.safety_assessment.escalation_triggered for r in results_by_profile.values())
        parts: list[str] = []
        if escalated_any and safety_consistency_verified:
            parts.append(
                "Mandatory system-level safety safeguards triggered identically across every evaluated "
                "organisation, preventing any profile from suppressing the hazard escalation."
            )
        if divergent_dims:
            parts.append(
                f"Recommendations differed on [{', '.join(divergent_dims)}] because each organisation "
                "defines independent categories, priority scales, and category-to-team routing rules."
            )
        else:
            parts.append("All compared profiles produced aligned outcomes on the evaluated dimensions.")
        return " ".join(parts)
