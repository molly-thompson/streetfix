"""Public reporting and intake models."""

from collections.abc import Iterable
from typing import Any

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.base import ModelBase


class ContactMethod(models.Model):
    """A fixed contact method with an administrator-editable label."""

    code = models.CharField(max_length=40, unique=True, editable=False)
    label = models.CharField(max_length=100)

    class Meta:
        ordering = ("code",)

    def __str__(self) -> str:
        """Return the configurable label."""
        return self.label


class Reporter(models.Model):
    """A person who submits a public report."""

    name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    telephone = models.CharField(max_length=40, blank=True)
    address = models.TextField(blank=True)

    def __str__(self) -> str:
        """Return the reporter's available display name."""
        return self.name or self.email or f"Reporter {self.pk}"


class ReportSubmission(models.Model):
    """A public submission, optionally linked to internal work."""

    class TriageState(models.TextChoices):
        """Current outcome of intake triage."""

        RECEIVED = "RECEIVED", "Received"
        NEEDS_REVIEW = "NEEDS_REVIEW", "Needs review"
        ACCEPTED = "ACCEPTED", "Accepted"
        DUPLICATE = "DUPLICATE", "Duplicate"
        OUT_OF_SCOPE = "OUT_OF_SCOPE", "Out of scope"
        LEGACY_LINKED = "LEGACY_LINKED", "Legacy linked"

    class ReportedImpact(models.TextChoices):
        """Reporter-provided impact evidence, not a priority decision."""

        UNKNOWN = "UNKNOWN", "Not sure"
        LIMITED = "LIMITED", "Limited"
        MODERATE = "MODERATE", "Moderate"
        SIGNIFICANT = "SIGNIFICANT", "Significant"
        SEVERE = "SEVERE", "Severe"

    class ReportedTimeSensitivity(models.TextChoices):
        """Reporter-provided timing evidence, not an urgency decision."""

        UNKNOWN = "UNKNOWN", "Not sure"
        ROUTINE = "ROUTINE", "Routine"
        NEAR_TERM = "NEAR_TERM", "Near term"
        PROMPT = "PROMPT", "Prompt"
        IMMEDIATE = "IMMEDIATE", "Immediate"

    class ReportedSensitiveContent(models.TextChoices):
        """Reporter-provided sensitive-content evidence."""

        UNKNOWN = "UNKNOWN", "Not sure"
        YES = "YES", "Yes"
        NO = "NO", "No"

    work_item = models.ForeignKey(
        "employees.WorkItem",
        on_delete=models.PROTECT,
        related_name="submissions",
        null=True,
        blank=True,
    )
    reporter = models.ForeignKey(
        Reporter,
        on_delete=models.SET_NULL,
        related_name="submissions",
        null=True,
        blank=True,
    )
    contact_method = models.ForeignKey(
        ContactMethod,
        on_delete=models.PROTECT,
        related_name="submissions",
        null=True,
        blank=True,
    )
    updates_requested = models.BooleanField()
    description = models.TextField()
    reported_issue_type = models.ForeignKey(
        "employees.IssueType",
        on_delete=models.PROTECT,
        related_name="reported_submissions",
        null=True,
        blank=True,
    )
    reported_issue_path = models.JSONField(default=list, blank=True)
    other_selected = models.BooleanField(default=False)
    location_description = models.TextField(blank=True)
    reported_impact = models.CharField(
        max_length=15,
        choices=ReportedImpact,
        default=ReportedImpact.UNKNOWN,
    )
    reported_time_sensitivity = models.CharField(
        max_length=15,
        choices=ReportedTimeSensitivity,
        default=ReportedTimeSensitivity.UNKNOWN,
    )
    reported_sensitive_content = models.CharField(
        max_length=10,
        choices=ReportedSensitiveContent,
        default=ReportedSensitiveContent.UNKNOWN,
    )
    latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[MinValueValidator(-90), MaxValueValidator(90)],
        null=True,
        blank=True,
    )
    longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        validators=[MinValueValidator(-180), MaxValueValidator(180)],
        null=True,
        blank=True,
    )
    triage_state = models.CharField(
        max_length=20,
        choices=TriageState,
        default=TriageState.RECEIVED,
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-submitted_at",)
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(latitude__isnull=True, longitude__isnull=True)
                    | Q(latitude__isnull=False, longitude__isnull=False)
                ),
                name="submission_coordinates_both_present_or_absent",
            ),
        ]

    def __str__(self) -> str:
        """Identify the submission."""
        return f"Submission {self.pk}"

    def clean(self) -> None:
        """Require complete coordinates when a map pin is provided."""
        super().clean()
        if (self.latitude is None) != (self.longitude is None):
            raise ValidationError("Provide both latitude and longitude for a map pin.")


class TriageAttemptQuerySet(models.QuerySet["TriageAttempt"]):
    """Prevent bulk edits and deletions of recorded triage attempts."""

    def update(self, **kwargs: Any) -> int:
        """Keep recorded attempts unchanged."""
        raise ValidationError("Triage attempts cannot be changed.")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Keep recorded attempts from bulk deletion."""
        raise ValidationError("Triage attempts cannot be deleted.")


class TriageAttempt(models.Model):
    """A recorded rules, AI, or human assessment of a submission."""

    class Stage(models.TextChoices):
        """Origin of the assessment."""

        RULES = "RULES", "Rules"
        AI = "AI", "AI"
        HUMAN = "HUMAN", "Human"

    submission = models.ForeignKey(
        ReportSubmission,
        on_delete=models.PROTECT,
        related_name="triage_attempts",
    )
    stage = models.CharField(max_length=10, choices=Stage)
    policy_version = models.CharField(max_length=100, blank=True)
    field_outcomes = models.JSONField(default=dict, blank=True)
    evidence = models.JSONField(default=dict, blank=True)
    decision = models.CharField(max_length=100, blank=True)
    reason = models.TextField(blank=True)
    reviewer = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        related_name="triage_attempts",
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    objects = TriageAttemptQuerySet.as_manager()

    class Meta:
        ordering = ("created_at", "pk")

    def __str__(self) -> str:
        """Identify the recorded assessment."""
        return f"{self.get_stage_display()} triage for submission {self.submission_id}"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Keep an existing attempt unchanged through the model interface."""
        if not self._state.adding:
            raise ValidationError("Triage attempts cannot be changed.")
        super().save(
            force_insert=force_insert,
            force_update=force_update,
            using=using,
            update_fields=update_fields,
        )

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Keep an existing attempt through the model interface."""
        raise ValidationError("Triage attempts cannot be deleted.")


class ReportSubmissionPhoto(models.Model):
    """A photo attached to a public report submission."""

    report_submission = models.ForeignKey(
        ReportSubmission,
        on_delete=models.CASCADE,
        related_name="photos",
    )
    image_url = models.URLField(max_length=2048)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("uploaded_at", "pk")

    def __str__(self) -> str:
        """Identify the parent submission."""
        return f"Photo for submission {self.report_submission_id}"
