"""Process durable advisory triage requests."""

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db.models import Q
from django.utils import timezone

from intake.models import TriageEngineJob
from intake.services.triage.engine import LEASE_MINUTES, _configuration, process_job


class Command(BaseCommand):
    """Run a bounded batch of pending or abandoned assessments."""

    help = "Process queued engine assessments; schedule and monitor this command."

    def add_arguments(self, parser: CommandParser) -> None:
        """Limit each worker run."""
        parser.add_argument("--limit", type=int, default=20)

    def handle(self, *args: object, **options: object) -> None:
        """Process each request outside any long-lived database transaction."""
        limit = options["limit"]
        if not isinstance(limit, int) or limit <= 0:
            raise CommandError("--limit must be a positive integer.")
        try:
            _configuration()
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        cutoff = timezone.now() - timedelta(minutes=LEASE_MINUTES)
        ids = list(
            TriageEngineJob.objects.filter(
                Q(status=TriageEngineJob.Status.PENDING)
                | Q(status=TriageEngineJob.Status.PROCESSING, started_at__lt=cutoff)
            )
            .order_by("created_at", "pk")
            .values_list("pk", flat=True)[:limit]
        )
        processed = sum(process_job(job_id) for job_id in ids)
        failed = TriageEngineJob.objects.filter(
            pk__in=ids, status=TriageEngineJob.Status.FAILED
        ).count()
        self.stdout.write(f"Processed {processed} assessments; {failed} failed.")
        if failed:
            raise CommandError("Some engine assessments failed.")
