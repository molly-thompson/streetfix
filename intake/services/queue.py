"""Queries for the central intake review queue."""

from django.db.models import BooleanField, Case, Q, QuerySet, Value, When

from intake.models import ReportSubmission


def pending_reviews() -> QuerySet[ReportSubmission]:
    """Include recovery cases and place immediate reports first."""
    return (
        ReportSubmission.objects.filter(
            triage_state__in=(
                ReportSubmission.TriageState.RECEIVED,
                ReportSubmission.TriageState.NEEDS_REVIEW,
            )
        )
        .select_related("reported_issue_type")
        .annotate(
            queue_urgent=Case(
                When(
                    Q(urgent_review=True)
                    | Q(
                        reported_time_sensitivity=(
                            ReportSubmission.ReportedTimeSensitivity.IMMEDIATE
                        )
                    ),
                    then=Value(True),
                ),
                default=Value(False),
                output_field=BooleanField(),
            )
        )
        .order_by("-queue_urgent", "submitted_at", "pk")
    )
