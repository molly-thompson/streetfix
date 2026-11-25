from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Any

from intake.services.reportmatch.models import (
    GenericReport,
    MatchingConfig,
    SignalAssessment,
)

STOP_WORDS: set[str] = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "been",
    "being",
    "but",
    "by",
    "for",
    "from",
    "had",
    "has",
    "have",
    "he",
    "her",
    "here",
    "hers",
    "him",
    "his",
    "i",
    "if",
    "in",
    "into",
    "is",
    "it",
    "its",
    "just",
    "me",
    "my",
    "no",
    "not",
    "of",
    "on",
    "or",
    "our",
    "out",
    "outside",
    "over",
    "reported",
    "report",
    "issue",
    "problem",
    "near",
    "next",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "this",
    "those",
    "through",
    "to",
    "too",
    "under",
    "up",
    "very",
    "was",
    "we",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
    "you",
    "your",
    "please",
    "needs",
    "causing",
}

CONCEPT_GROUPS: list[tuple[str, list[str]]] = [
    (
        "road_surface_defect",
        [
            r"\bpotholes?\b",
            r"\b(massive|deep|large|huge|dangerous)\s+hole\b",
            r"\bhole\s+in\s+(the\s+)?(road|tarmac|carriageway|asphalt|street)\b",
            r"\b(road|tarmac|asphalt|carriageway)\s+(surface\s+)?(is\s+)?(badly\s+)?(damaged|broken|cracked|sunken|crumbling|collapsed)\b",
            r"\bcrater\b",
            r"\bsubsidence\b",
            r"\btarmac\b",
            r"\bcarriageway\b",
            r"\basphalt\b",
        ],
    ),
    (
        "pavement_trip_hazard",
        [
            r"\bpavement\b",
            r"\bfootway\b",
            r"\bfootpath\b",
            r"\bsidewalk\b",
            r"\bpaving\s+(slab|stone)s?\b",
            r"\btrip(ping)?\s+hazard\b",
            r"\bkerb(stone)?s?\b",
            r"\bcurb\b",
        ],
    ),
    (
        "street_lighting_fault",
        [
            r"\bstreet\s*lights?\b",
            r"\blamp\s*posts?\b",
            r"\bstreet\s*lamps?\b",
            r"\blantern\b",
            r"\bpitch\s*black\b",
            r"\bdarkness\b",
            r"\blights?\s+(is\s+|are\s+)?(out|off|broken|dead|flickering|not\s+working)\b",
        ],
    ),
    (
        "dumped_waste",
        [
            r"\bfly[\s-]*tip(ping|ped)?\b",
            r"\bdumped\s+(rubbish|waste|trash|bags|furniture|mattress|debris)\b",
            r"\bbin\s+bags\b",
            r"\bblack\s+bags\b",
            r"\bmattress\b",
            r"\billegal(ly)?\s+dump(ed|ing)\b",
            r"\brubbish\s+pile\b",
            r"\bwaste\s+piled\b",
        ],
    ),
    (
        "drainage_flooding",
        [
            r"\b(blocked|clogged|overflowing)\s+(storm\s+)?(drain|gully|grate|culvert)\b",
            r"\bdrains?\b",
            r"\bgully\b",
            r"\bstanding\s+water\b",
            r"\bflood(ing|ed)?\b",
            r"\bwater\s+pooling\b",
            r"\bpuddle\b",
        ],
    ),
    (
        "water_leak_moisture",
        [
            r"\bwater\s+(dripping|leaking|pouring|seeping|gushing)\b",
            r"\bburst\s+pipe\b",
            r"\bpipe\s+leak(ing)?\b",
            r"\bceiling\s+leak\b",
            r"\boverflowing\s+(washing\s+machine|tank|pipe|bath)\b",
            r"\bdamp(ness)?\b",
            r"\bmould\b",
            r"\bmold\b",
            r"\bcondensation\b",
            r"\bwater\s+stains?\b",
            r"\bwater\s+ingress\b",
        ],
    ),
    (
        "heating_hvac_fault",
        [
            r"\bheating\s+(is\s+)?(off|broken|failed|failure|down|not\s+working)\b",
            r"\bhvac\b",
            r"\bradiators?\s+(are\s+)?(stone\s+)?cold\b",
            r"\bboiler\s+(fault|error|broken|down|off)\b",
            r"\bfreezing\b",
            r"\bno\s+hot\s+water\b",
            r"\bthermostat\b",
            r"\bno\s+heat(ing)?\b",
        ],
    ),
    (
        "av_equipment_fault",
        [
            r"\bprojector\b",
            r"\bhdmi\b",
            r"\bno\s+signal\b",
            r"\bflickering\s+(screen|display|image)\b",
            r"\bav\s+(system|equipment|rack)\b",
            r"\blectern\b",
        ],
    ),
    (
        "vegetation_tree_hazard",
        [
            r"\bfallen\s+(tree|branch(es)?)\b",
            r"\btree\s+(down|blocking|collapsed)\b",
            r"\bovergrown\s+(hedge|branches|trees)\b",
            r"\bblocking\s+(the\s+)?(path|road|lane|towpath)\b",
        ],
    ),
    (
        "graffiti_damage",
        [
            r"\bgraffiti\b",
            r"\bspray\s*paint(ed)?\b",
            r"\bvandali(sm|sed|zed)\b",
            r"\btagged\b",
        ],
    ),
    (
        "fire_door_safety",
        [
            r"\bfire\s+door\b",
            r"\bcloser\s+(broken|disconnected)\b",
            r"\bwedged\s+open\b",
            r"\bwill\s+not\s+latch\b",
            r"\bdoor\s+(jammed|broken|won't\s+close)\b",
        ],
    ),
]

STREET_SUFFIXES = (
    r"(?:street|st|road|rd|lane|ln|avenue|ave|drive|dr|way|close|cl|parade|"
    r"crescent|cres|terrace|place|pl|square|sq|grove|hill|walk|underpass|towpath|"
    r"court|house|block|building|hall|wing|centre|center|park)"
)

STREET_REGEX = re.compile(
    rf"\b([a-z0-9][a-z0-9'\-]*(?:\s+[a-z0-9][a-z0-9'\-]*){{0,2}}\s+{STREET_SUFFIXES})\b",
    re.IGNORECASE,
)

SUFFIX_NORMALIZATION = {
    "st": "street",
    "rd": "road",
    "ln": "lane",
    "ave": "avenue",
    "dr": "drive",
    "cl": "close",
    "cres": "crescent",
    "pl": "place",
    "sq": "square",
    "ctr": "centre",
    "center": "centre",
}


def normalize_place_phrase(raw: str) -> str:
    cleaned = re.sub(r"['’.,]", " ", raw.lower())
    words = [SUFFIX_NORMALIZATION.get(w, w) for w in cleaned.split()]
    leading_trim = {
        "on",
        "in",
        "at",
        "of",
        "the",
        "near",
        "outside",
        "by",
        "from",
        "along",
        "behind",
        "opposite",
        "to",
        "and",
        "for",
        "with",
    }
    while len(words) > 2 and words[0] in leading_trim:
        words.pop(0)
    return " ".join(words)


def extract_named_places(report: GenericReport) -> list[str]:
    texts = [
        report.location.address
        if report.location and report.location.address
        else None,
        report.location.locationDescription
        if report.location and report.location.locationDescription
        else None,
        report.location.zone if report.location and report.location.zone else None,
        report.title,
        report.description,
    ]
    found: set[str] = set()
    for t in texts:
        if not t:
            continue
        for m in STREET_REGEX.findall(t):
            norm = normalize_place_phrase(m)
            if len(norm.split()) >= 2:
                found.add(norm)
    return sorted(found)


def haversine_distance_meters(
    lat1: float, lon1: float, lat2: float, lon2: float
) -> int:
    r = 6371000
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    a = min(1.0, max(0.0, a))
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return int(round(r * c))


def evaluate_geographical_signal(
    incoming: GenericReport,
    candidate: GenericReport,
    config: MatchingConfig,
) -> SignalAssessment:
    weight = config.weights.geographical
    d_dup = config.thresholds.maxDuplicateDistanceMeters
    d_rel = config.thresholds.relatedDistanceMeters
    evidence: list[str] = []
    contradictions: list[str] = []
    metrics: dict[str, Any] = {}

    in_places = extract_named_places(incoming)
    cand_places = extract_named_places(candidate)
    shared_places = [p for p in in_places if p in cand_places]

    if (
        incoming.location is not None
        and incoming.location.latitude is not None
        and incoming.location.longitude is not None
        and candidate.location is not None
        and candidate.location.latitude is not None
        and candidate.location.longitude is not None
    ):
        dist = haversine_distance_meters(
            incoming.location.latitude,
            incoming.location.longitude,
            candidate.location.latitude,
            candidate.location.longitude,
        )
        metrics["distanceMeters"] = dist

        if dist <= d_dup:
            ratio = dist / d_dup
            score = round(1.0 - ratio * 0.16, 3)
            evidence.append(
                f"Coordinates are {dist}m apart (within {d_dup}m duplicate radius)."
            )
        elif dist <= d_rel:
            ratio = (dist - d_dup) / max(1.0, d_rel - d_dup)
            score = round(0.84 - ratio * 0.34, 3)
            evidence.append(
                f"Coordinates are {dist}m apart (within {d_rel}m related vicinity)."
            )
        elif dist <= d_rel * 2.2:
            ratio = (dist - d_rel) / max(1.0, d_rel * 1.2)
            score = round(0.49 - ratio * 0.34, 3)
            contradictions.append(
                f"Coordinates are {dist}m apart, outside the {d_rel}m vicinity threshold."
            )
            metrics["hardSpatialMismatch"] = True
        else:
            score = round(max(0.02, 0.14 - min(0.12, dist / 20000.0)), 3)
            contradictions.append(
                f"Locations are {dist / 1000.0:.2f}km apart — distinct geographic locations."
            )
            metrics["hardSpatialMismatch"] = True

        if shared_places:
            evidence.append(f"Shared place reference: {', '.join(shared_places)}.")
        elif in_places and cand_places and dist > d_dup:
            contradictions.append(
                f"Different street/building references ({in_places[0]} vs {cand_places[0]})."
            )
            metrics["hardSpatialMismatch"] = True

        return SignalAssessment(
            key="geographical",
            label="Geographical Proximity",
            score=score,
            weight=weight,
            effectiveWeight=weight,
            weightedContribution=round(score * weight, 4),
            status="evaluated",
            summary=f"{dist}m separation"
            + (f" · {shared_places[0]}" if shared_places else ""),
            evidence=evidence,
            contradictions=contradictions,
            metrics=metrics,
        )

    # Fallback to textual street/building/zone matching
    if in_places and cand_places:
        if shared_places:
            evidence.append(
                f"Matched place reference ({', '.join(shared_places)}), though GPS coordinates are incomplete."
            )
            return SignalAssessment(
                key="geographical",
                label="Geographical Proximity",
                score=0.78,
                weight=weight,
                effectiveWeight=weight,
                weightedContribution=round(0.78 * weight, 4),
                status="partial",
                summary=f"Matched place ({shared_places[0]}), GPS incomplete",
                evidence=evidence,
                contradictions=contradictions,
                metrics={**metrics, "missingCoordinates": True},
            )
        contradictions.append(
            f"Conflicting street or building references: '{in_places[0]}' vs '{cand_places[0]}'."
        )
        return SignalAssessment(
            key="geographical",
            label="Geographical Proximity",
            score=0.08,
            weight=weight,
            effectiveWeight=weight,
            weightedContribution=round(0.08 * weight, 4),
            status="partial",
            summary=f"Different named locations ({in_places[0]} vs {cand_places[0]})",
            evidence=evidence,
            contradictions=contradictions,
            metrics={
                **metrics,
                "hardSpatialMismatch": True,
                "missingCoordinates": True,
            },
        )

    in_zone = (
        incoming.location.zone.strip().lower()
        if incoming.location and incoming.location.zone
        else None
    )
    cand_zone = (
        candidate.location.zone.strip().lower()
        if candidate.location and candidate.location.zone
        else None
    )
    if in_zone and cand_zone:
        same_zone = in_zone == cand_zone
        score = 0.52 if same_zone else 0.15
        if same_zone:
            evidence.append(f"Both reports reference zone '{in_zone}'.")
        else:
            contradictions.append(f"Different zones ({in_zone} vs {cand_zone}).")
        return SignalAssessment(
            key="geographical",
            label="Geographical Proximity",
            score=score,
            weight=weight,
            effectiveWeight=weight,
            weightedContribution=round(score * weight, 4),
            status="partial",
            summary=f"Zone match ({in_zone})" if same_zone else "Different zones",
            evidence=evidence,
            contradictions=contradictions,
            metrics={
                **metrics,
                "missingCoordinates": True,
                "hardSpatialMismatch": not same_zone,
            },
        )

    return SignalAssessment(
        key="geographical",
        label="Geographical Proximity",
        score=None,
        weight=weight,
        effectiveWeight=0.0,
        weightedContribution=0.0,
        status="missing",
        summary="Insufficient location data to verify spatial proximity",
        evidence=[],
        contradictions=[],
        metrics={"missingCoordinates": True},
    )


def evaluate_temporal_signal(
    incoming: GenericReport,
    candidate: GenericReport,
    config: MatchingConfig,
) -> SignalAssessment:
    weight = config.weights.temporal
    dup_window = config.thresholds.duplicateTimeWindowHours
    rec_gap = config.thresholds.recurringMinGapHours
    evidence: list[str] = []
    contradictions: list[str] = []

    if not incoming.reportedAt or not candidate.reportedAt:
        return SignalAssessment(
            key="temporal",
            label="Temporal Window",
            score=None,
            weight=weight,
            effectiveWeight=0.0,
            weightedContribution=0.0,
            status="missing",
            summary="Timestamp missing on one or both reports",
            evidence=[],
            contradictions=[],
        )

    try:
        t1 = datetime.fromisoformat(incoming.reportedAt.replace("Z", "+00:00"))
        t2 = datetime.fromisoformat(candidate.reportedAt.replace("Z", "+00:00"))
    except ValueError:
        return SignalAssessment(
            key="temporal",
            label="Temporal Window",
            score=None,
            weight=weight,
            effectiveWeight=0.0,
            weightedContribution=0.0,
            status="missing",
            summary="Invalid timestamp format",
            evidence=[],
            contradictions=[],
        )

    hours_apart = abs((t1 - t2).total_seconds()) / 3600.0
    days_apart = round(hours_apart / 24.0, 1)
    is_recurring = False

    if hours_apart <= 24.0:
        score = round(1.0 - (hours_apart / 24.0) * 0.08, 3)
        evidence.append(f"Submitted within {hours_apart:.1f} hours of each other.")
    elif hours_apart <= dup_window:
        ratio = (hours_apart - 24.0) / max(1.0, dup_window - 24.0)
        score = round(0.92 - ratio * 0.24, 3)
        evidence.append(
            f"Submitted {days_apart} days apart (within {int(dup_window / 24)}-day duplicate window)."
        )
    elif hours_apart < rec_gap:
        ratio = (hours_apart - dup_window) / max(1.0, rec_gap - dup_window)
        score = round(0.67 - ratio * 0.32, 3)
        contradictions.append(
            f"Submitted {days_apart} days apart, outside the {int(dup_window / 24)}-day duplicate window."
        )
    else:
        is_recurring = True
        score = round(max(0.08, 0.28 - min(0.2, (hours_apart - rec_gap) / 2000.0)), 3)
        contradictions.append(
            f"Reported {days_apart} days apart — exceeds recurring threshold ({int(rec_gap / 24)} days); likely recurring or separate historical incident."
        )

    return SignalAssessment(
        key="temporal",
        label="Temporal Window",
        score=score,
        weight=weight,
        effectiveWeight=weight,
        weightedContribution=round(score * weight, 4),
        status="evaluated",
        summary=f"{hours_apart:.1f} hrs apart"
        if hours_apart < 48
        else f"{days_apart} days apart" + (" (recurring gap)" if is_recurring else ""),
        evidence=evidence,
        contradictions=contradictions,
        metrics={
            "hoursApart": round(hours_apart, 1),
            "daysApart": days_apart,
            "isRecurringTimeGap": is_recurring,
        },
    )


def evaluate_categorical_signal(
    incoming: GenericReport,
    candidate: GenericReport,
    config: MatchingConfig,
) -> SignalAssessment:
    weight = config.weights.categorical
    cat_a = incoming.category.strip().lower() if incoming.category else None
    cat_b = candidate.category.strip().lower() if candidate.category else None
    sub_a = incoming.subcategory.strip().lower() if incoming.subcategory else None
    sub_b = candidate.subcategory.strip().lower() if candidate.subcategory else None

    if not cat_a or not cat_b:
        return SignalAssessment(
            key="categorical",
            label="Categorical Alignment",
            score=None,
            weight=weight,
            effectiveWeight=0.0,
            weightedContribution=0.0,
            status="missing",
            summary="Issue category missing on one or both reports",
            evidence=[],
            contradictions=[],
        )

    evidence: list[str] = []
    contradictions: list[str] = []
    is_related_cat = False
    is_distinct_cat = False

    if cat_a == cat_b:
        if sub_a and sub_b and sub_a == sub_b:
            score = 1.0
            evidence.append(
                f"Exact category and subcategory match ({cat_a} / {sub_a})."
            )
        elif sub_a and sub_b and sub_a != sub_b:
            score = 0.78
            evidence.append(
                f"Same category ({cat_a}), different subcategories ({sub_a} vs {sub_b})."
            )
        else:
            score = 0.90
            evidence.append(f"Matching primary category ({cat_a}).")
    else:
        in_related = any(
            cat_a in grp and cat_b in grp for grp in config.categoryRules.relatedGroups
        )
        in_incompatible = any(
            cat_a in grp and cat_b in grp
            for grp in config.categoryRules.incompatibleGroups
        )
        if in_incompatible:
            score = 0.10
            is_distinct_cat = True
            contradictions.append(
                f"Distinct incompatible categories ({cat_a} vs {cat_b})."
            )
        elif in_related:
            score = 0.62
            is_related_cat = True
            evidence.append(f"Related categories ({cat_a} ↔ {cat_b}).")
        else:
            score = 0.20
            is_distinct_cat = True
            contradictions.append(f"Different issue categories ({cat_a} vs {cat_b}).")

    return SignalAssessment(
        key="categorical",
        label="Categorical Alignment",
        score=score,
        weight=weight,
        effectiveWeight=weight,
        weightedContribution=round(score * weight, 4),
        status="evaluated",
        summary=f"Same category ({cat_a})"
        if cat_a == cat_b
        else f"Related ({cat_a} ↔ {cat_b})"
        if is_related_cat
        else f"Distinct ({cat_a} ≠ {cat_b})",
        evidence=evidence,
        contradictions=contradictions,
        metrics={
            "sameCategory": cat_a == cat_b,
            "isRelatedCategory": is_related_cat,
            "isDistinctCategory": is_distinct_cat,
        },
    )


def extract_unit_and_asset_tokens(report: GenericReport) -> dict[str, list[str]]:
    combined = " ".join(
        [
            report.title or "",
            report.description or "",
            (
                report.location.address
                if report.location and report.location.address
                else ""
            ),
            (
                report.location.locationDescription
                if report.location and report.location.locationDescription
                else ""
            ),
        ]
    ).lower()

    unit_refs: set[str] = set()
    asset_refs: set[str] = set()
    landmarks: set[str] = set()

    for m in re.findall(
        r"\b(?:flat|apt|apartment|unit|room|suite|lecture\s*theatre|bay)\s*[#:]?\s*[a-z0-9]{1,5}\b",
        combined,
    ):
        unit_refs.add(re.sub(r"[#:\s]+", " ", m).strip())

    for m in re.findall(
        r"\b(?:lamp\s*post|column|pole|hydrant|camera|bin|lift|boiler)\s*(?:#|no\.?|number)?\s*[a-z0-9\-]{1,6}\b",
        combined,
    ):
        asset_refs.add(re.sub(r"[#:\s]+", " ", m).strip())

    landmark_keywords = [
        "shops",
        "junction",
        "traffic lights",
        "crossing",
        "bus stop",
        "roundabout",
        "primary school",
        "school",
        "library",
        "station",
        "park",
        "towpath",
        "canal",
        "car park",
        "alley",
        "underpass",
        "chemists",
        "bakery",
        "supermarket",
        "tesco",
        "bridge",
        "communal hallway",
        "stairwell",
        "basement",
        "roof",
    ]
    for lm in landmark_keywords:
        if lm in combined:
            landmarks.add(lm)

    if report.metadata:
        for k, v in report.metadata.items():
            if v is None or v == "":
                continue
            k_low = k.lower()
            v_low = str(v).lower().strip()
            if any(term in k_low for term in ["room", "flat", "unit"]):
                unit_refs.add(f"{k_low}:{v_low}")
            if any(term in k_low for term in ["asset", "pole", "column"]):
                asset_refs.add(f"{k_low}:{v_low}")

    return {
        "unitRefs": list(unit_refs),
        "assetRefs": list(asset_refs),
        "landmarks": list(landmarks),
    }


def evaluate_contextual_signal(
    incoming: GenericReport,
    candidate: GenericReport,
    config: MatchingConfig,
) -> SignalAssessment:
    weight = config.weights.contextual
    ctx_a = extract_unit_and_asset_tokens(incoming)
    ctx_b = extract_unit_and_asset_tokens(candidate)
    evidence: list[str] = []
    contradictions: list[str] = []

    matches = 0
    comparisons = 0
    conflicting_unit = False
    conflicting_landmark = False

    if ctx_a["unitRefs"] and ctx_b["unitRefs"]:
        comparisons += 1
        shared_units = [u for u in ctx_a["unitRefs"] if u in ctx_b["unitRefs"]]
        if shared_units:
            matches += 1
            evidence.append(
                f"Matching unit/room identifier ({', '.join(shared_units)})."
            )
        else:
            conflicting_unit = True
            contradictions.append(
                f"Different unit/room references ({ctx_a['unitRefs'][0]} vs {ctx_b['unitRefs'][0]})."
            )

    if ctx_a["assetRefs"] and ctx_b["assetRefs"]:
        comparisons += 1
        shared_assets = [a for a in ctx_a["assetRefs"] if a in ctx_b["assetRefs"]]
        if shared_assets:
            matches += 1
            evidence.append(f"Matching asset identifier ({', '.join(shared_assets)}).")
        else:
            contradictions.append(
                f"Different asset identifiers ({ctx_a['assetRefs'][0]} vs {ctx_b['assetRefs'][0]})."
            )

    meta_a = incoming.metadata or {}
    meta_b = candidate.metadata or {}
    for k in set(meta_a.keys()).intersection(meta_b.keys()):
        if k == "reporterType":
            continue
        comparisons += 1
        va = str(meta_a[k]).lower().strip()
        vb = str(meta_b[k]).lower().strip()
        if va == vb:
            matches += 1
            evidence.append(f"Matching metadata {k}: '{meta_a[k]}'.")
        elif k.lower() in ["building", "block", "assetid", "room", "flat"]:
            conflicting_unit = True
            contradictions.append(
                f"Conflicting {k} metadata ('{meta_a[k]}' vs '{meta_b[k]}')."
            )

    if ctx_a["landmarks"] and ctx_b["landmarks"]:
        comparisons += 1
        shared_lm = [l for l in ctx_a["landmarks"] if l in ctx_b["landmarks"]]
        if shared_lm:
            matches += 1
            evidence.append(f"Shared contextual landmark: {', '.join(shared_lm)}.")
        else:
            if ("park" in ctx_a["landmarks"] and "towpath" in ctx_b["landmarks"]) or (
                "towpath" in ctx_a["landmarks"] and "park" in ctx_b["landmarks"]
            ):
                conflicting_landmark = True
            contradictions.append(
                f"Different surrounding landmarks ({ctx_a['landmarks'][0]} vs {ctx_b['landmarks'][0]})."
            )

    if comparisons == 0:
        return SignalAssessment(
            key="contextual",
            label="Contextual Details",
            score=None,
            weight=weight,
            effectiveWeight=0.0,
            weightedContribution=0.0,
            status="missing",
            summary="No comparable asset IDs or unit refs",
            evidence=[],
            contradictions=[],
        )

    raw_score = matches / comparisons
    if conflicting_unit or conflicting_landmark:
        raw_score = min(raw_score, 0.25)
    score = round(max(0.05, min(1.0, raw_score)), 3)

    return SignalAssessment(
        key="contextual",
        label="Contextual Details",
        score=score,
        weight=weight,
        effectiveWeight=weight,
        weightedContribution=round(score * weight, 4),
        status="evaluated",
        summary=evidence[0]
        if evidence
        else (contradictions[0] if contradictions else "Contextual assessed"),
        evidence=evidence,
        contradictions=contradictions,
        metrics={
            "conflictingUnitRef": conflicting_unit,
            "conflictingLandmark": conflicting_landmark,
            "sharedFeaturesCount": matches,
        },
    )


def extract_concepts(text: str) -> list[str]:
    low = text.lower()
    concepts: set[str] = set()
    for concept, patterns in CONCEPT_GROUPS:
        for p in patterns:
            if re.search(p, low):
                concepts.add(concept)
                break
    return list(concepts)


def tokenize(text: str) -> list[str]:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", re.sub(r"['’]", "", text.lower()))
    tokens: list[str] = []
    for w in cleaned.split():
        if len(w) >= 2 and w not in STOP_WORDS:
            if w.endswith("ing") and len(w) > 5:
                w = w[:-3]
            elif w.endswith("ed") and len(w) > 4:
                w = w[:-2]
            elif w.endswith("s") and len(w) > 4 and not w.endswith("ss"):
                w = w[:-1]
            tokens.append(w)
    return tokens


def char_trigrams(text: str) -> dict[str, int]:
    cleaned = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()
    counts: dict[str, int] = {}
    for i in range(len(cleaned) - 2):
        tri = cleaned[i : i + 3]
        counts[tri] = counts.get(tri, 0) + 1
    return counts


def trigram_cosine(m1: dict[str, int], m2: dict[str, int]) -> float:
    dot = sum(v * m2[k] for k, v in m1.items() if k in m2)
    norm1 = sum(v * v for v in m1.values())
    norm2 = sum(v * v for v in m2.values())
    if norm1 == 0 or norm2 == 0:
        return 0.0
    return dot / (math.sqrt(norm1) * math.sqrt(norm2))


def jaccard(l1: list[str], l2: list[str]) -> float:
    s1, s2 = set(l1), set(l2)
    if not s1 and not s2:
        return 0.0
    intersection = len(s1.intersection(s2))
    union = len(s1.union(s2))
    return intersection / union if union > 0 else 0.0


def evaluate_deterministic_semantic_signal(
    incoming: GenericReport,
    candidate: GenericReport,
    config: MatchingConfig,
) -> SignalAssessment:
    weight = config.weights.semantic
    text_a = ". ".join(filter(None, [incoming.title, incoming.description]))
    text_b = ". ".join(filter(None, [candidate.title, candidate.description]))

    concepts_a = extract_concepts(text_a)
    concepts_b = extract_concepts(text_b)
    shared_concepts = [c for c in concepts_a if c in concepts_b]

    tokens_a = tokenize(text_a)
    tokens_b = tokenize(text_b)
    shared_tokens = list(set(tokens_a).intersection(set(tokens_b)))

    concept_overlap = (
        (2 * len(shared_concepts)) / (len(concepts_a) + len(concepts_b))
        if concepts_a and concepts_b
        else 0.0
    )
    token_sim = jaccard(tokens_a, tokens_b)
    tri_sim = trigram_cosine(char_trigrams(text_a), char_trigrams(text_b))

    if concepts_a and concepts_b:
        score = concept_overlap * 0.56 + token_sim * 0.24 + tri_sim * 0.20
        if shared_concepts:
            score = max(score, 0.62 + concept_overlap * 0.25)
    else:
        score = token_sim * 0.55 + tri_sim * 0.45

    score = round(max(0.02, min(0.98, score)), 3)
    evidence: list[str] = []
    contradictions: list[str] = []

    if shared_concepts:
        evidence.append(
            f"Shared domain concepts: {', '.join(c.replace('_', ' ') for c in shared_concepts)}."
        )
    if shared_tokens:
        evidence.append(f"Key overlapping terms: {', '.join(shared_tokens[:6])}.")
    if concepts_a and concepts_b and not shared_concepts:
        contradictions.append(
            f"Descriptions describe different core concepts: {', '.join(concepts_a)} vs {', '.join(concepts_b)}."
        )

    return SignalAssessment(
        key="semantic",
        label="Semantic Similarity",
        score=score,
        weight=weight,
        effectiveWeight=weight,
        weightedContribution=round(score * weight, 4),
        status="evaluated",
        summary=(
            f"Aligned concepts ({shared_concepts[0].replace('_', ' ')})"
            if shared_concepts
            else (
                f"Lexical overlap ({', '.join(shared_tokens[:3])})"
                if shared_tokens
                else "Low semantic overlap"
            )
        ),
        evidence=evidence,
        contradictions=contradictions,
        metrics={
            "sharedConceptsCount": len(shared_concepts),
            "tokenJaccard": round(token_sim, 3),
        },
    )
