from __future__ import annotations

import uuid
from datetime import UTC, datetime

from intake.services.reportmatch.models import (
    ConfidenceBand,
    DuplicateDetectionRequest,
    DuplicateDetectionResponse,
    GenericReport,
    IncomingReportSummary,
    MatchAssessment,
    MatchClassification,
    MatchingConfig,
    ReviewRecommendation,
    SignalAssessment,
    SignalKey,
    SummaryStats,
)
from intake.services.reportmatch.signals import (
    evaluate_categorical_signal,
    evaluate_contextual_signal,
    evaluate_deterministic_semantic_signal,
    evaluate_geographical_signal,
    evaluate_temporal_signal,
)

CLASSIFICATION_LABELS: dict[MatchClassification, str] = {
    "likely_duplicate": "Likely duplicate",
    "related_reports": "Related reports",
    "similar_but_unrelated": "Similar but unrelated",
    "unrelated": "Unrelated",
}

RECOMMENDATION_LABELS: dict[ReviewRecommendation, str] = {
    "review_together": "Review together for potential consolidation",
    "link_as_related": "Link as related incidents (keep separate)",
    "monitor_recurring": "Flag as recurring issue at same location",
    "no_action": "Treat as separate report (no link required)",
}


def summarize_incoming_report(report: GenericReport) -> IncomingReportSummary:
    missing_fields: list[str] = []
    available_signals: list[SignalKey] = ["semantic"]

    if (
        report.location
        and report.location.latitude is not None
        and report.location.longitude is not None
    ):
        available_signals.append("geographical")
    elif report.location and (
        report.location.address or report.location.locationDescription
    ):
        available_signals.append("geographical")
        missing_fields.append("location.coordinates")
    else:
        missing_fields.extend(["location.coordinates", "location.address"])

    if report.reportedAt:
        available_signals.append("temporal")
    else:
        missing_fields.append("reportedAt")

    if report.category:
        available_signals.append("categorical")
    else:
        missing_fields.append("category")

    if report.metadata:
        available_signals.append("contextual")
    else:
        missing_fields.append("metadata")

    return IncomingReportSummary(
        id=report.id,
        availableSignals=available_signals,
        missingFields=missing_fields,
        completenessRatio=round(len(available_signals) / 5.0, 2),
    )


def classify_pair(
    signals: dict[SignalKey, SignalAssessment],
    composite_score: float,
    config: MatchingConfig,
) -> tuple[MatchClassification, ReviewRecommendation, ConfidenceBand, list[str], str]:
    thresh = config.thresholds
    uncertainty: list[str] = []

    available = [
        s for s in signals.values() if s.status != "missing" and s.score is not None
    ]
    avail_count = len(available)

    sem_score = signals["semantic"].score or 0.0
    geo_score = signals["geographical"].score
    cat_score = signals["categorical"].score

    geo_metrics = signals["geographical"].metrics
    hard_spatial_mismatch = bool(geo_metrics.get("hardSpatialMismatch"))
    missing_coords = bool(geo_metrics.get("missingCoordinates"))
    is_recurring = bool(signals["temporal"].metrics.get("isRecurringTimeGap"))
    is_related_cat = bool(signals["categorical"].metrics.get("isRelatedCategory"))
    is_distinct_cat = bool(signals["categorical"].metrics.get("isDistinctCategory"))
    conflicting_unit = bool(signals["contextual"].metrics.get("conflictingUnitRef"))
    conflicting_lm = bool(signals["contextual"].metrics.get("conflictingLandmark"))

    if avail_count < thresh.minimumSignalsAvailable:
        uncertainty.append(
            f"Only {avail_count} of {thresh.minimumSignalsAvailable} minimum signals were available; human verification is essential."
        )
    if signals["geographical"].status == "missing":
        uncertainty.append(
            "Geographical details missing on one or both reports; spatial coincidence unverified."
        )
    elif missing_coords:
        uncertainty.append(
            "GPS coordinates incomplete; spatial proximity relies on extracted street/place names."
        )
    if signals["temporal"].status == "missing":
        uncertainty.append("Missing timestamp prevents verifying active time window.")
    if signals["categorical"].status == "missing":
        uncertainty.append("Missing category prevents verifying issue-type alignment.")

    # Gate 1: Hard spatial or landmark contradiction -> cannot be duplicate
    if hard_spatial_mismatch or conflicting_lm:
        if sem_score >= thresh.similarUnrelatedSemanticMin:
            return (
                "similar_but_unrelated",
                "no_action",
                "high" if avail_count >= 3 else "medium",
                uncertainty,
                "Descriptions are semantically similar, but geographical or landmark evidence shows the reports refer to different locations.",
            )
        return (
            "unrelated",
            "no_action",
            "high",
            uncertainty,
            "Reports refer to different locations and lack evidence of a shared incident.",
        )

    # Gate 2: Co-located divergence (different unit or incompatible categories)
    co_located = geo_score is not None and geo_score >= 0.68
    if co_located and conflicting_unit:
        if (
            sem_score >= 0.45
            or is_related_cat
            or (cat_score is not None and cat_score >= 0.6)
        ):
            return (
                "related_reports",
                "link_as_related",
                "medium",
                uncertainty,
                "Reports share the same building or vicinity with connected symptoms, but reference different rooms or units.",
            )
        return (
            "similar_but_unrelated",
            "no_action",
            "medium",
            uncertainty,
            "Reports occur in the same vicinity with similar wording, but point to distinct units or assets.",
        )

    if co_located and is_distinct_cat:
        return (
            "related_reports",
            "link_as_related",
            "medium",
            uncertainty,
            "Reports refer to the same location, but describe distinctly different issue categories — co-located separate issues.",
        )

    # Gate 3: Recurring historical gap
    if is_recurring:
        if sem_score >= thresh.semanticDuplicateThreshold and (
            geo_score is None or geo_score >= 0.65
        ):
            return (
                "related_reports",
                "monitor_recurring",
                "high" if geo_score is not None else "medium",
                uncertainty,
                "Issue description and location match closely, but the time gap exceeds the recurring threshold — flag as recurring problem.",
            )
        return (
            "similar_but_unrelated"
            if sem_score >= thresh.similarUnrelatedSemanticMin
            else "unrelated",
            "no_action",
            "medium",
            uncertainty,
            "Reports are separated by a long time window and lack evidence of being the same active incident.",
        )

    # Gate 4: Likely duplicate check
    has_geo_support = geo_score is not None and geo_score >= 0.65
    missing_geo_strong_text = (
        signals["geographical"].status == "missing"
        and sem_score >= 0.68
        and (cat_score is None or cat_score >= 0.8)
    )

    if (
        composite_score >= thresh.likelyDuplicateScore
        and sem_score >= thresh.semanticDuplicateThreshold
        and (has_geo_support or missing_geo_strong_text)
        and avail_count >= thresh.minimumSignalsAvailable
    ):
        conf_band: ConfidenceBand = (
            "high"
            if signals["geographical"].status == "evaluated"
            and avail_count >= 4
            and composite_score >= min(0.95, thresh.likelyDuplicateScore + 0.08)
            else "medium"
        )
        exp = (
            "Descriptions and category strongly align within the active timeframe, though missing GPS coordinates introduce uncertainty."
            if missing_geo_strong_text
            else "High alignment across semantic meaning, spatial proximity, category, and timeframe indicates these reports likely describe the same underlying issue."
        )
        return ("likely_duplicate", "review_together", conf_band, uncertainty, exp)

    # Gate 5: Related reports
    if (
        composite_score >= thresh.relatedReportScore
        or (co_located and (is_related_cat or sem_score >= 0.42))
        or (signals["geographical"].status == "missing" and sem_score >= 0.58)
    ):
        return (
            "related_reports",
            "link_as_related",
            "medium" if avail_count >= 3 else "low",
            uncertainty,
            "Reports share overlapping location or connected categories and may stem from a shared underlying cause.",
        )

    # Gate 6: Similar but unrelated
    if sem_score >= thresh.similarUnrelatedSemanticMin:
        return (
            "similar_but_unrelated",
            "no_action",
            "medium",
            uncertainty,
            "Reports share similar terminology or issue descriptions, but other signals do not support a shared incident.",
        )

    # Gate 7: Unrelated
    return (
        "unrelated",
        "no_action",
        "high",
        uncertainty,
        "Insufficient semantic, spatial, and contextual alignment to indicate a meaningful relationship.",
    )


def detect_duplicates(
    request: DuplicateDetectionRequest,
    config: MatchingConfig,
) -> DuplicateDetectionResponse:
    incoming = request.incomingReport
    candidates = [c for c in request.existingReports if c.id != incoming.id]
    request_id = f"det_{uuid.uuid4().hex[:12]}"
    processed_at = datetime.now(UTC).isoformat()

    if config.mode != "deterministic":
        raise ValueError("Only deterministic matching is supported.")

    assessments: list[MatchAssessment] = []
    for cand in candidates:
        det_sem = evaluate_deterministic_semantic_signal(incoming, cand, config)
        geo = evaluate_geographical_signal(incoming, cand, config)
        temporal = evaluate_temporal_signal(incoming, cand, config)
        categorical = evaluate_categorical_signal(incoming, cand, config)
        contextual = evaluate_contextual_signal(incoming, cand, config)

        raw_signals: dict[SignalKey, SignalAssessment] = {
            "semantic": det_sem,
            "geographical": geo,
            "temporal": temporal,
            "categorical": categorical,
            "contextual": contextual,
        }

        # Dynamic weight renormalization
        available = [
            s
            for s in raw_signals.values()
            if s.status != "missing" and s.score is not None
        ]
        total_avail_w = sum(s.weight for s in available)

        composite_score = 0.0
        for s in raw_signals.values():
            if s.status != "missing" and s.score is not None and total_avail_w > 0:
                eff_w = s.weight / total_avail_w
                s.effectiveWeight = round(eff_w, 4)
                s.weightedContribution = round(s.score * eff_w, 4)
                composite_score += s.weightedContribution
            else:
                s.effectiveWeight = 0.0
                s.weightedContribution = 0.0

        if (
            categorical.metrics.get("sameCategory")
            and config.categoryRules.treatSameCategoryBonus > 0
        ):
            composite_score = min(
                1.0, composite_score + config.categoryRules.treatSameCategoryBonus
            )

        composite_score = round(max(0.0, min(1.0, composite_score)), 3)

        classification, rec, conf_band, uncert, explanation = classify_pair(
            raw_signals, composite_score, config
        )

        similarities: list[str] = []
        differences: list[str] = []
        contradictions: list[str] = []
        for s in raw_signals.values():
            similarities.extend(s.evidence)
            contradictions.extend(s.contradictions)

        if incoming.category and cand.category and incoming.category != cand.category:
            differences.append(
                f"Category differs: '{incoming.category}' vs '{cand.category}'."
            )
        dist = geo.metrics.get("distanceMeters")
        if dist is not None and dist > 0:
            differences.append(f"Reported coordinates are {dist}m apart.")
        days = temporal.metrics.get("daysApart")
        if days is not None and days >= 1.0:
            differences.append(f"Reported {days} days apart.")

        assessments.append(
            MatchAssessment(
                candidateReportId=cand.id,
                candidateReport=cand,
                classification=classification,
                classificationLabel=CLASSIFICATION_LABELS[classification],
                compositeScore=composite_score,
                scoreIsAdvisory=True,
                confidenceBand=conf_band,
                recommendation=rec,
                recommendationLabel=RECOMMENDATION_LABELS[rec],
                signalBreakdown=raw_signals,
                signalsAvailableCount=len(available),
                similarities=list(dict.fromkeys(similarities)),
                differences=list(dict.fromkeys(differences)),
                contradictions=list(dict.fromkeys(contradictions)),
                uncertaintyNotes=uncert,
                explanation=explanation,
                semanticSource="deterministic",
            )
        )

    # Sort: priority class order then compositeScore descending
    priority = {
        "likely_duplicate": 0,
        "related_reports": 1,
        "similar_but_unrelated": 2,
        "unrelated": 3,
    }
    assessments.sort(key=lambda a: (priority[a.classification], -a.compositeScore))

    return DuplicateDetectionResponse(
        requestId=request_id,
        processedAt=processed_at,
        engineVersion="1.0.0",
        advisoryNotice=(
            "Advisory output only: similarity scores reflect multi-signal matching strength rather than calibrated probabilities. "
            "An authorised reviewer must confirm or reject any suggested links before modifying records."
        ),
        effectiveConfig=config,
        incomingReportSummary=summarize_incoming_report(incoming),
        summaryStats=SummaryStats(
            totalCandidates=len(assessments),
            likelyDuplicates=sum(
                1 for a in assessments if a.classification == "likely_duplicate"
            ),
            relatedReports=sum(
                1 for a in assessments if a.classification == "related_reports"
            ),
            similarButUnrelated=sum(
                1 for a in assessments if a.classification == "similar_but_unrelated"
            ),
            unrelated=sum(1 for a in assessments if a.classification == "unrelated"),
            highestCompositeScore=max(
                (a.compositeScore for a in assessments), default=0.0
            ),
        ),
        assessments=assessments,
    )
