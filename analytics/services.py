"""Explainable exploratory analysis over organisational work records."""

from collections import Counter, defaultdict
from collections.abc import Iterable
from math import sqrt

from django.db.models import QuerySet
from django.utils import timezone

from employees.work_models import WorkItem

MIN_SAMPLE_SIZE = 20
MIN_CATEGORY_COUNT = 5


def _share_anomalies(
    records: list[dict[str, object]],
    field: str,
    label: str,
) -> list[dict[str, object]]:
    """Find categories whose concentration is unusually high for this dataset."""
    counts = Counter(str(record[field]) for record in records if record[field])
    total = sum(counts.values())
    if total < MIN_SAMPLE_SIZE:
        return []

    findings: list[dict[str, object]] = []
    category_count = len(counts)
    if category_count < 2:
        return findings
    baseline = 1 / category_count
    for category, count in counts.most_common():
        share = count / total
        standard_error = sqrt(max(baseline * (1 - baseline) / total, 0.000001))
        z_score = (share - baseline) / standard_error
        if count >= MIN_CATEGORY_COUNT and z_score >= 2:
            matching_ids = [
                record["id"] for record in records if str(record[field]) == category
            ]
            findings.append(
                {
                    "kind": "concentration",
                    "title": f"Unusually frequent {label}: {category}",
                    "description": (
                        f"{count} records use {category}, representing "
                        f"{share:.1%} of the records with a value for {label}."
                    ),
                    "variables": [label],
                    "observations": [
                        f"{count} records",
                        f"{share:.1%} share",
                        f"z-score {z_score:.2f}",
                    ],
                    "supporting_record_ids": matching_ids[:50],
                    "significance": "Descriptive statistical outlier",
                    "caveat": (
                        "This is an observed concentration, not evidence of cause."
                    ),
                }
            )
    return findings


def _categorical_associations(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    """Identify frequent pairs of dimensions without assuming a relationship."""
    fields = ("issue_type", "priority", "urgency", "status")
    findings: list[dict[str, object]] = []
    if len(records) < MIN_SAMPLE_SIZE:
        return findings

    for left_index, left in enumerate(fields):
        for right in fields[left_index + 1 :]:
            pair_counts: Counter[tuple[str, str]] = Counter()
            left_counts: Counter[str] = Counter()
            right_counts: Counter[str] = Counter()
            valid = 0
            for record in records:
                left_value = record[left]
                right_value = record[right]
                if not left_value or not right_value:
                    continue
                left_text = str(left_value)
                right_text = str(right_value)
                pair_counts[(left_text, right_text)] += 1
                left_counts[left_text] += 1
                right_counts[right_text] += 1
                valid += 1
            if valid < MIN_SAMPLE_SIZE:
                continue

            for (left_value, right_value), observed in pair_counts.most_common():
                if observed < MIN_CATEGORY_COUNT:
                    continue
                expected = left_counts[left_value] * right_counts[right_value] / valid
                lift = observed / expected if expected else 0
                if lift < 1.5:
                    continue
                matching_ids = [
                    record["id"]
                    for record in records
                    if str(record[left]) == left_value
                    and str(record[right]) == right_value
                ]
                findings.append(
                    {
                        "kind": "association",
                        "title": f"{left_value} is associated with {right_value}",
                        "description": (
                            f"{observed} records combine {left_value} with "
                            f"{right_value}, compared with {expected:.1f} expected "
                            "from their overall frequencies."
                        ),
                        "variables": [left, right],
                        "observations": [
                            f"{observed} observed records",
                            f"{expected:.1f} records expected",
                            f"{lift:.2f}x lift",
                        ],
                        "supporting_record_ids": matching_ids[:50],
                        "significance": "Frequent pair; association is descriptive",
                        "caveat": (
                            "Correlation does not establish causation or "
                            "exclude confounding variables."
                        ),
                    }
                )
    return sorted(
        findings,
        key=lambda finding: finding["observations"][-1],
        reverse=True,
    )[:12]


def _temporal_patterns(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Detect a recurring month or weekday concentration."""
    monthly: Counter[str] = Counter()
    weekdays: Counter[str] = Counter()
    for record in records:
        created_at = record["created_at"]
        if created_at is not None:
            monthly[str(created_at.strftime("%Y-%m"))] += 1
            weekdays[created_at.strftime("%A")] += 1
    findings: list[dict[str, object]] = []
    if sum(monthly.values()) >= MIN_SAMPLE_SIZE and len(monthly) >= 2:
        average = sum(monthly.values()) / len(monthly)
        for period, count in monthly.most_common():
            deviation = count - average
            if count >= MIN_CATEGORY_COUNT and deviation >= average:
                matching_ids = [
                    record["id"]
                    for record in records
                    if record["created_at"] is not None
                    and record["created_at"].strftime("%Y-%m") == period
                ]
                findings.append(
                    {
                        "kind": "temporal",
                        "title": f"Higher activity in {period}",
                        "description": (
                            f"{count} records were created in {period}, above the "
                            f"{average:.1f}-record average across observed months."
                        ),
                        "variables": ["created_at", "month"],
                        "observations": [
                            f"{count} records",
                            f"{average:.1f} per month",
                        ],
                        "supporting_record_ids": matching_ids[:50],
                        "significance": "Temporal concentration",
                        "caveat": (
                            "A recurring or seasonal explanation is a hypothesis "
                            "requiring comparison across more time periods."
                        ),
                    }
                )

    if sum(weekdays.values()) >= MIN_SAMPLE_SIZE and len(weekdays) >= 2:
        average = sum(weekdays.values()) / len(weekdays)
        for weekday, count in weekdays.most_common():
            if count >= MIN_CATEGORY_COUNT and count >= average * 1.5:
                matching_ids = [
                    record["id"]
                    for record in records
                    if record["created_at"] is not None
                    and record["created_at"].strftime("%A") == weekday
                ]
                findings.append(
                    {
                        "kind": "temporal",
                        "title": f"Higher activity on {weekday}",
                        "description": (
                            f"{count} records were created on {weekday}, compared "
                            f"with a {average:.1f}-record average per weekday."
                        ),
                        "variables": ["created_at", "weekday"],
                        "observations": [
                            f"{count} records",
                            f"{average:.1f} per weekday",
                        ],
                        "supporting_record_ids": matching_ids[:50],
                        "significance": "Temporal concentration",
                        "caveat": (
                            "This may reflect reporting, assignment or data-entry "
                            "behaviour rather than a real-world pattern."
                        ),
                    }
                )
    return findings[:8]


def _geographical_patterns(records: list[dict[str, object]]) -> list[dict[str, object]]:
    """Cluster coordinates on a coarse grid so patterns remain explainable."""
    clusters: dict[tuple[str, str], list[int]] = defaultdict(list)
    for record in records:
        latitude = record["latitude"]
        longitude = record["longitude"]
        if latitude is None or longitude is None:
            continue
        lat_key = round(float(latitude) * 100) / 100
        lng_key = round(float(longitude) * 100) / 100
        clusters[(str(lat_key), str(lng_key))].append(int(record["id"]))

    total = sum(len(ids) for ids in clusters.values())
    if total < MIN_SAMPLE_SIZE:
        return []
    average = total / len(clusters)
    findings: list[dict[str, object]] = []
    for (latitude, longitude), record_ids in sorted(
        clusters.items(),
        key=lambda item: len(item[1]),
        reverse=True,
    ):
        count = len(record_ids)
        if count < MIN_CATEGORY_COUNT or count < average * 2:
            continue
        findings.append(
            {
                "kind": "geographical",
                "title": f"Concentration near {latitude}, {longitude}",
                "description": (
                    f"{count} records occur in a coarse grid area of roughly "
                    "0.01 degrees, above the dataset-wide cluster average."
                ),
                "variables": ["latitude", "longitude"],
                "observations": [
                    f"{count} records",
                    f"{average:.1f} records per occupied grid area",
                ],
                "supporting_record_ids": record_ids[:50],
                "significance": "Geographical concentration",
                "caveat": (
                    "The grid is approximate; neighbouring records should be "
                    "inspected before drawing a boundary or cause."
                ),
            }
        )
    return findings[:8]


def discover_patterns(
    work_items: Iterable[WorkItem] | QuerySet[WorkItem] | None = None,
) -> dict[str, object]:
    """Return bounded, traceable exploratory findings for work items."""
    queryset = (
        work_items if isinstance(work_items, QuerySet) else WorkItem.objects.all()
    )
    if work_items is not None and not isinstance(work_items, QuerySet):
        queryset = WorkItem.objects.filter(
            pk__in=[work_item.pk for work_item in work_items]
        )
    queryset = queryset.select_related(
        "issue_type",
        "priority",
        "urgency",
        "status",
    ).order_by("-created_at")

    records = [
        {
            "id": work_item.pk,
            "issue_type": work_item.issue_type.name,
            "priority": work_item.priority.label,
            "urgency": work_item.urgency.label,
            "status": work_item.status.label,
            "latitude": work_item.latitude,
            "longitude": work_item.longitude,
            "created_at": work_item.created_at,
        }
        for work_item in queryset
    ]
    findings: list[dict[str, object]] = []
    for field, label in (
        ("issue_type", "issue type"),
        ("priority", "priority"),
        ("urgency", "urgency"),
        ("status", "status"),
    ):
        findings.extend(_share_anomalies(records, field, label))
    findings.extend(_categorical_associations(records))
    findings.extend(_temporal_patterns(records))
    findings.extend(_geographical_patterns(records))

    if len(records) < MIN_SAMPLE_SIZE:
        limitations = (
            f"Only {len(records)} records are available; findings require at "
            f"least {MIN_SAMPLE_SIZE} records."
        )
    else:
        limitations = "No finding implies causation; inspect supporting records."

    return {
        "record_count": len(records),
        "findings": findings[:30],
        "limitations": limitations,
        "generated_at": timezone.now(),
    }
