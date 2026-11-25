"""Public reporting and intake models."""

import secrets
from collections.abc import Iterable
from typing import Any
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, router, transaction
from django.db.models import Q
from django.db.models.base import ModelBase

PUBLIC_REFERENCE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PUBLIC_REFERENCE_LENGTH = 8


def new_public_reference() -> str:
    """Return a random, unambiguous code that cannot be guessed or counted."""
    return "".join(
        secrets.choice(PUBLIC_REFERENCE_ALPHABET)
        for _ in range(PUBLIC_REFERENCE_LENGTH)
    )


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
    urgent_review = models.BooleanField(default=False)
    public_reference = models.CharField(
        max_length=12,
        unique=True,
        default=new_public_reference,
        editable=False,
        help_text="Random code a reporter can quote; reveals nothing about volume.",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-submitted_at",)
        permissions = [
            ("review_reportsubmission", "Can review report submissions"),
        ]
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


class PolicyDefinitionQuerySet(models.QuerySet[Any]):
    """Prevent bulk writes that bypass policy lifecycle checks."""

    def update(self, **kwargs: Any) -> int:
        """Require individual draft edits or an authorized transition."""
        raise ValidationError("Policy definitions cannot be bulk updated.")

    def delete(self) -> tuple[int, dict[str, int]]:
        """Require individual draft deletion."""
        raise ValidationError("Policy definitions cannot be bulk deleted.")

    def bulk_create(self, *args: Any, **kwargs: Any) -> list[Any]:
        """Require lifecycle checks for each definition."""
        raise ValidationError("Policy definitions cannot be bulk created.")

    def bulk_update(self, *args: Any, **kwargs: Any) -> int:
        """Require lifecycle checks for each definition."""
        raise ValidationError("Policy definitions cannot be bulk updated.")


class TriagePolicy(models.Model):
    """A versioned context policy for deterministic triage."""

    class Status(models.TextChoices):
        """A policy is editable only before activation."""

        DRAFT = "DRAFT", "Draft"
        ACTIVE = "ACTIVE", "Active"
        RETIRED = "RETIRED", "Retired"

    version = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=150)
    status = models.CharField(max_length=10, choices=Status, default=Status.DRAFT)
    service_area = models.JSONField(null=True, blank=True)
    evidence_labels = models.JSONField(default=dict, blank=True)
    urgent_review_phrases = models.JSONField(default=list, blank=True)
    taxonomy_snapshot = models.JSONField(null=True, editable=False)
    duplicate_distance_m = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(20_000_000)],
    )
    duplicate_age_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(365_000)],
    )
    created_at = models.DateTimeField(auto_now_add=True)
    activated_at = models.DateTimeField(null=True, blank=True)
    activated_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        related_name="activated_triage_policies",
        null=True,
        blank=True,
    )
    objects = PolicyDefinitionQuerySet.as_manager()

    class Meta:
        ordering = ("-version",)
        permissions = [("activate_triagepolicy", "Can activate triage policies")]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        duplicate_distance_m__isnull=True,
                        duplicate_age_days__isnull=True,
                    )
                    | Q(
                        duplicate_distance_m__gte=1,
                        duplicate_distance_m__lte=20_000_000,
                        duplicate_distance_m__isnull=False,
                        duplicate_age_days__gte=1,
                        duplicate_age_days__lte=365_000,
                        duplicate_age_days__isnull=False,
                    )
                ),
                name="triage_policy_duplicate_window_complete",
            ),
            models.UniqueConstraint(
                fields=("status",),
                condition=Q(status="ACTIVE"),
                name="one_active_triage_policy",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="DRAFT", activated_at__isnull=True)
                    | Q(status__in=("ACTIVE", "RETIRED"), activated_at__isnull=False)
                ),
                name="triage_policy_activation_time_consistent",
            ),
        ]

    def __str__(self) -> str:
        """Identify a policy version."""
        return f"{self.name} (version {self.version})"

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Allow normal writes only to drafts; transitions use the approval service."""
        alias = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=alias):
            if self.status != self.Status.DRAFT:
                raise ValidationError("Policy status must be changed through approval.")
            if not self._state.adding:
                previous = (
                    type(self)
                    ._base_manager.using(alias)
                    .select_for_update()
                    .get(pk=self.pk)
                )
                if previous.status != self.Status.DRAFT:
                    raise ValidationError("Activated policies cannot be changed.")
            super().save(
                force_insert=force_insert,
                force_update=force_update,
                using=alias,
                update_fields=update_fields,
            )

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Never delete an activated policy version."""
        alias = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=alias):
            previous = (
                type(self)
                ._base_manager.using(alias)
                .select_for_update()
                .get(pk=self.pk)
            )
            if previous.status != self.Status.DRAFT:
                raise ValidationError("Activated policies cannot be deleted.")
            return super().delete(using=alias, keep_parents=keep_parents)

    def clean(self) -> None:
        """Validate geographic coverage and bounded policy presentation."""
        super().clean()
        errors: dict[str, Any] = {}
        if (self.duplicate_distance_m is None) != (self.duplicate_age_days is None):
            errors["duplicate_distance_m"] = (
                "Provide both duplicate-search distance and age, or neither."
            )
        if self.service_area is not None:
            from intake.services.triage.geography import parse_service_area

            try:
                parse_service_area(self.service_area)
            except ValidationError as exc:
                errors["service_area"] = exc.messages
        from intake.services.triage.labels import validate_evidence_labels
        from intake.services.triage.urgent import validate_urgent_phrases

        try:
            validate_urgent_phrases(self.urgent_review_phrases)
        except ValidationError as exc:
            errors["urgent_review_phrases"] = exc.messages
        try:
            validate_evidence_labels(self.evidence_labels)
        except ValidationError as exc:
            errors["evidence_labels"] = exc.messages
        if errors:
            raise ValidationError(errors)


class DraftPolicyDefinition(models.Model):
    """Serialize definition changes with the policy approval transition."""

    objects = PolicyDefinitionQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(
        self,
        *,
        force_insert: bool | tuple[ModelBase, ...] = False,
        force_update: bool = False,
        using: str | None = None,
        update_fields: Iterable[str] | None = None,
    ) -> None:
        """Only change definitions while their policy is a draft."""
        alias = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=alias):
            self._lock_draft_policy(alias)
            super().save(
                force_insert=force_insert,
                force_update=force_update,
                using=alias,
                update_fields=update_fields,
            )

    def delete(
        self, using: str | None = None, keep_parents: bool = False
    ) -> tuple[int, dict[str, int]]:
        """Only remove definitions while their policy is a draft."""
        alias = using or router.db_for_write(type(self), instance=self)
        with transaction.atomic(using=alias):
            self._lock_draft_policy(alias)
            return super().delete(using=alias, keep_parents=keep_parents)

    def _lock_draft_policy(self, alias: str) -> None:
        policy_id = self.policy_id  # type: ignore[attr-defined]
        if not policy_id:
            raise ValidationError("A draft policy is required.")
        if not self._state.adding:
            previous_id = (
                type(self)
                ._base_manager.using(alias)
                .filter(pk=self.pk)
                .values_list("policy_id", flat=True)  # type: ignore[misc]
                .first()
            )
            if previous_id != policy_id:
                raise ValidationError("A policy definition cannot be moved.")
        policy = (
            TriagePolicy._base_manager.using(alias)
            .select_for_update()
            .get(pk=policy_id)
        )
        if policy.status != TriagePolicy.Status.DRAFT:
            raise ValidationError("Activated policy definitions cannot be changed.")


class TriagePolicyRule(DraftPolicyDefinition):
    """A bounded evidence match and its fixed priority or urgency outcome."""

    class Target(models.TextChoices):
        """The output field addressed by this rule."""

        PRIORITY = "PRIORITY", "Priority"
        URGENCY = "URGENCY", "Urgency"

    policy = models.ForeignKey(
        TriagePolicy, on_delete=models.PROTECT, related_name="rules"
    )
    name = models.CharField(max_length=150)
    issue_type = models.ForeignKey(
        "employees.IssueType",
        on_delete=models.PROTECT,
        related_name="triage_rules",
        null=True,
        blank=True,
    )
    impact = models.CharField(
        max_length=15,
        choices=[
            choice
            for choice in ReportSubmission.ReportedImpact.choices
            if choice[0] != "UNKNOWN"
        ],
        blank=True,
    )
    time_sensitivity = models.CharField(
        max_length=15,
        choices=[
            choice
            for choice in ReportSubmission.ReportedTimeSensitivity.choices
            if choice[0] != "UNKNOWN"
        ],
        blank=True,
    )
    sensitive_content = models.CharField(
        max_length=10,
        choices=[
            choice
            for choice in ReportSubmission.ReportedSensitiveContent.choices
            if choice[0] != "UNKNOWN"
        ],
        blank=True,
    )
    target = models.CharField(max_length=10, choices=Target)
    outcome_code = models.CharField(max_length=10)

    class Meta:
        ordering = ("name", "pk")
        constraints = [
            models.UniqueConstraint(
                fields=("policy", "name"), name="unique_triage_rule_name_per_policy"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        target="PRIORITY",
                        outcome_code__in=("LOW", "NORMAL", "HIGH", "CRITICAL"),
                    )
                    | Q(
                        target="URGENCY",
                        outcome_code__in=("ROUTINE", "SOON", "URGENT", "EMERGENCY"),
                    )
                ),
                name="triage_rule_target_outcome_consistent",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(impact="") | ~Q(time_sensitivity="") | ~Q(sensitive_content="")
                ),
                name="triage_rule_requires_evidence",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(target="URGENCY")
                    | Q(sensitive_content="")
                    | ~Q(time_sensitivity="")
                ),
                name="sensitive_urgency_requires_time_evidence",
            ),
        ]

    def __str__(self) -> str:
        """Return the rule's policy-specific name."""
        return self.name

    def clean(self) -> None:
        """Require sensitive modifiers to be scoped to relevant issue types."""
        super().clean()
        issue_type = self.issue_type if self.issue_type_id else None
        if self.sensitive_content and (
            issue_type is None or not issue_type.sensitive_content_enabled
        ):
            raise ValidationError(
                {
                    "issue_type": (
                        "Choose an issue type with sensitive-content evidence enabled."
                    )
                }
            )


class TriagePolicyScenario(DraftPolicyDefinition):
    """A staff-authored example of expected deterministic policy outcomes."""

    class ExpectedState(models.TextChoices):
        """Expected outcome from a set of bounded rules."""

        DETERMINED = "determined", "Determined"
        AMBIGUOUS = "ambiguous", "Ambiguous"
        CONFLICTING = "conflicting", "Conflicting"

    policy = models.ForeignKey(
        TriagePolicy, on_delete=models.PROTECT, related_name="scenarios"
    )
    name = models.CharField(max_length=150)
    issue_type = models.ForeignKey(
        "employees.IssueType",
        on_delete=models.PROTECT,
        related_name="triage_scenarios",
        null=True,
        blank=True,
    )
    impact = models.CharField(
        max_length=15,
        choices=ReportSubmission.ReportedImpact,
        default=ReportSubmission.ReportedImpact.UNKNOWN,
    )
    time_sensitivity = models.CharField(
        max_length=15,
        choices=ReportSubmission.ReportedTimeSensitivity,
        default=ReportSubmission.ReportedTimeSensitivity.UNKNOWN,
    )
    sensitive_content = models.CharField(
        max_length=10,
        choices=ReportSubmission.ReportedSensitiveContent,
        default=ReportSubmission.ReportedSensitiveContent.UNKNOWN,
    )
    priority_state = models.CharField(max_length=12, choices=ExpectedState)
    priority_code = models.CharField(max_length=10, blank=True)
    urgency_state = models.CharField(max_length=12, choices=ExpectedState)
    urgency_code = models.CharField(max_length=10, blank=True)

    def __str__(self) -> str:
        """Identify the policy example."""
        return self.name

    def clean(self) -> None:
        """Require outcome codes only for determined expected results."""
        super().clean()
        errors: dict[str, str] = {}
        for field, state, code, allowed in (
            (
                "priority_code",
                self.priority_state,
                self.priority_code,
                ("LOW", "NORMAL", "HIGH", "CRITICAL"),
            ),
            (
                "urgency_code",
                self.urgency_state,
                self.urgency_code,
                ("ROUTINE", "SOON", "URGENT", "EMERGENCY"),
            ),
        ):
            if state == self.ExpectedState.DETERMINED:
                if code not in allowed:
                    errors[field] = "Choose a valid outcome for a determined result."
            elif code:
                errors[field] = (
                    "Leave the outcome empty when the result is not determined."
                )
        if self.sensitive_content != ReportSubmission.ReportedSensitiveContent.UNKNOWN:
            issue_type = self.issue_type if self.issue_type_id else None
            if issue_type is None or not issue_type.sensitive_content_enabled:
                errors["sensitive_content"] = (
                    "Sensitive evidence requires an issue type where it is enabled."
                )
        if errors:
            raise ValidationError(errors)


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


class RateLimitRecord(models.Model):
    """Rolling request history for one public action and pseudonymous address."""

    scope = models.CharField(max_length=40)
    address_digest = models.CharField(max_length=64)
    timestamps = models.JSONField(default=list)
    last_hit_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("scope", "address_digest"),
                name="unique_rate_limit_per_scope_and_address",
            )
        ]

    def __str__(self) -> str:
        """Identify the record without exposing its digest."""
        return f"{self.scope} rate limit {self.pk}"


class ReportPhotoDraft(models.Model):
    """A session-bound collection of reserved photo uploads."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    session_digest = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)
    submission = models.OneToOneField(
        ReportSubmission,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="photo_draft",
    )

    def __str__(self) -> str:
        """Identify the draft without exposing its session binding."""
        return f"Report photo draft {self.pk}"


class ReportPhotoSlot(models.Model):
    """A server-generated asset reservation within a photo draft."""

    id = models.UUIDField(primary_key=True, default=uuid4, editable=False)
    draft = models.ForeignKey(
        ReportPhotoDraft, on_delete=models.PROTECT, related_name="slots"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    asset_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    format = models.CharField(max_length=10, blank=True)
    size_bytes = models.PositiveIntegerField(null=True, blank=True)
    version = models.PositiveBigIntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        asset_id__isnull=True,
                        format="",
                        size_bytes__isnull=True,
                        version__isnull=True,
                    )
                    | (
                        Q(
                            asset_id__isnull=False,
                            size_bytes__isnull=False,
                            version__isnull=False,
                            size_bytes__gte=1,
                            size_bytes__lte=10_000_000,
                            version__gte=1,
                        )
                        & ~Q(asset_id="")
                        & Q(format__in=("jpg", "jpeg", "png", "webp", "heic"))
                    )
                ),
                name="report_photo_slot_verification_complete",
            ),
        ]

    def __str__(self) -> str:
        """Identify the reserved slot."""
        return f"Report photo slot {self.pk}"

    @property
    def public_id(self) -> str:
        """Return the fixed Cloudinary public ID reserved for this slot."""
        return f"intake/report-photos/{self.pk.hex}"
