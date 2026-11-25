"""Remove expired rate-limit records."""

from django.core.management.base import BaseCommand
from django.utils import timezone

from intake.models import RateLimitRecord
from intake.services.rate_limit import LONGEST_WINDOW


class Command(BaseCommand):
    """Keep only addresses with activity inside the longest active window."""

    help = "Delete expired public rate-limit records."

    def handle(self, *args: object, **options: object) -> None:
        """Prune records that can no longer affect any rolling limit."""
        cutoff = timezone.now() - LONGEST_WINDOW
        count, _ = RateLimitRecord.objects.filter(last_hit_at__lte=cutoff).delete()
        self.stdout.write(f"Deleted {count} expired rate-limit records.")
