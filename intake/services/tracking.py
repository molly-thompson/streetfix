"""Let a reporter follow the reports they submitted, without an account.

Reporters are usually anonymous, so a browser remembers the public references
of reports it submitted (or that were looked up by reference) in its session.
Only references are stored; the dashboard reads current status each time.
"""

from collections.abc import MutableMapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from django.utils import timezone

from intake.models import ReportSubmission
from intake.services.reference import (
    display_reference,
    public_status,
    submission_for_reference,
)
from site_settings.configuration import get_site_configuration

SESSION_KEY = "tracked_report_references"


@dataclass(frozen=True)
class TrackedReport:
    """What a reporter may see about one of their reports."""

    reference: str
    issue: str
    status: str
    submitted_at: datetime
    days_open: int
    is_finished: bool


def _codes(session: MutableMapping[str, Any]) -> list[str]:
    stored = session.get(SESSION_KEY, [])
    return [code for code in stored if isinstance(code, str)]


def remember_report(
    session: MutableMapping[str, Any], submission: ReportSubmission
) -> bool:
    """Follow a report in this browser; return False when the limit is reached."""
    codes = _codes(session)
    if submission.public_reference in codes:
        return True
    if len(codes) >= get_site_configuration().public_tracking_max_reports:
        return False
    session[SESSION_KEY] = [submission.public_reference, *codes]
    return True


def remember_reference(session: MutableMapping[str, Any], reference: str) -> bool:
    """Follow the report behind a typed reference; False if none matches."""
    submission = submission_for_reference(reference)
    if submission is None:
        return False
    return remember_report(session, submission)


def forget_reference(session: MutableMapping[str, Any], reference: str) -> None:
    """Stop following a report in this browser."""
    submission = submission_for_reference(reference)
    if submission is None:
        return
    session[SESSION_KEY] = [
        code for code in _codes(session) if code != submission.public_reference
    ]


def tracked_reports(session: MutableMapping[str, Any]) -> list[TrackedReport]:
    """Return the followed reports, newest first."""
    codes = _codes(session)
    if not codes:
        return []
    submissions = ReportSubmission.objects.select_related(
        "work_item__status", "reported_issue_type"
    ).filter(public_reference__in=codes)
    now = timezone.now()
    reports = []
    for submission in submissions:
        work_item = submission.work_item
        status = work_item.status if work_item is not None else None
        reports.append(
            TrackedReport(
                reference=display_reference(submission),
                issue=str(submission.reported_issue_type or "Other"),
                status=public_status(submission),
                submitted_at=submission.submitted_at,
                days_open=(now - submission.submitted_at).days,
                is_finished=status is not None
                and (status.is_resolved or status.is_ended or status.is_cancelled),
            )
        )
    return sorted(reports, key=lambda report: report.submitted_at, reverse=True)
