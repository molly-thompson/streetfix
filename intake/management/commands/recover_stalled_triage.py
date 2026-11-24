"""Recover persisted submissions whose post-commit triage did not finish."""

import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import transaction
from django.utils import timezone

from intake.models import ReportSubmission
from intake.services.review import request_review
from intake.services.triage.orchestrator import triage_submission

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """Retry a bounded batch of old received submissions."""

    help = "Retry triage for received reports older than the specified age."

    def add_arguments(self, parser: CommandParser) -> None:
        """Require an operator-selected age and limit the batch size."""
        parser.add_argument("--older-than-minutes", required=True, type=int)
        parser.add_argument("--limit", default=100, type=int)

    def handle(self, *args: object, **options: object) -> None:
        """Retry each report under a lock, or route a failed retry to review."""
        age = options["older_than_minutes"]
        limit = options["limit"]
        if not isinstance(age, int) or age <= 0:
            raise CommandError("--older-than-minutes must be a positive integer.")
        if not isinstance(limit, int) or limit <= 0:
            raise CommandError("--limit must be a positive integer.")
        cutoff = timezone.now() - timedelta(minutes=age)
        ids = list(
            ReportSubmission.objects.filter(
                triage_state=ReportSubmission.TriageState.RECEIVED,
                submitted_at__lte=cutoff,
            )
            .order_by("submitted_at", "pk")
            .values_list("pk", flat=True)[:limit]
        )
        failed = 0
        recovered = 0
        for submission_id in ids:
            try:
                with transaction.atomic():
                    submission = ReportSubmission.objects.select_for_update().get(
                        pk=submission_id
                    )
                    if submission.triage_state != ReportSubmission.TriageState.RECEIVED:
                        continue
                    try:
                        triage_submission(submission_id)
                    except Exception:
                        logger.exception("Triage retry failed for %s", submission_id)
                        request_review(
                            submission_id, reason="Automated triage retry failed."
                        )
                    recovered += 1
            except Exception:
                failed += 1
                logger.exception("Recovery failed for %s", submission_id)
        self.stdout.write(f"Recovered {recovered} stalled reports; {failed} failed.")
        if failed:
            raise CommandError("Some stalled reports could not be recovered.")
