"""Admin configuration for public reporting models."""

# mypy: disable-error-code=type-arg

from typing import Any, ClassVar

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache

from employees.organisation_models import Employee
from intake.forms import PolicyApprovalForm
from intake.models import (
    ContactMethod,
    IssueCategory,
    IssueCategoryKeyword,
    IssueSubcategory,
    Reporter,
    ReportSubmission,
    ReportSubmissionPhoto,
    SlaPolicy,
    TriageAttempt,
    TriageEngineJob,
    TriagePolicy,
    TriagePolicyRule,
    TriagePolicyScenario,
)
from intake.services.triage.pilot import summarize_pilot
from intake.services.triage.policy import activate_policy
from intake.services.triage.scenarios import evaluate_scenarios


@admin.register(TriageEngineJob)
class TriageEngineJobAdmin(admin.ModelAdmin):
    """Expose assessments read-only to authorized pilot evaluators."""

    list_display = ("submission", "status", "profile", "created_at", "finished_at")
    list_filter = ("status", "visible_to_reviewers")
    readonly_fields = (
        "submission",
        "requested_by",
        "status",
        "policy_version",
        "profile",
        "config_digest",
        "configuration_snapshot",
        "input_digest",
        "visible_to_reviewers",
        "started_at",
        "created_at",
        "finished_at",
        "result",
        "error",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Only reviewer requests can create assessments."""
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: TriageEngineJob | None = None
    ) -> bool:
        """Recorded assessments cannot be edited in admin."""
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: TriageEngineJob | None = None
    ) -> bool:
        """Preserve assessment records in the admin."""
        return False


@admin.register(ContactMethod)
class ContactMethodAdmin(admin.ModelAdmin):
    """Allow label edits while keeping seeded contact methods fixed."""

    list_display: ClassVar[tuple[str, ...]] = (  # type: ignore[misc]
        "code",
        "label",
        "active",
        "sort_order",
    )
    list_editable: ClassVar[tuple[str, ...]] = ("label", "active", "sort_order")
    ordering = ("code",)
    readonly_fields = ("code",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent creation of contact methods outside the seed migration."""
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: ContactMethod | None = None,
    ) -> bool:
        """Prevent deletion of fixed contact methods."""
        return False


class IssueSubcategoryInline(admin.TabularInline):
    """Edit category sub-options alongside the category."""

    model = IssueSubcategory
    extra = 0


class IssueCategoryKeywordInline(admin.TabularInline):
    """Edit category keyword rules alongside the category."""

    model = IssueCategoryKeyword
    extra = 0


@admin.register(IssueCategory)
class IssueCategoryAdmin(admin.ModelAdmin):
    """Admin configuration for public issue categories."""

    list_display = (
        "code",
        "label",
        "issue_type",
        "active",
        "sort_order",
    )
    list_editable = ("label", "active", "sort_order")
    list_filter = ("active", ("issue_type", admin.EmptyFieldListFilter))
    search_fields = ("code", "label", "issue_type__name", "issue_type__code")
    fields = (
        "code",
        "issue_type",
        "label",
        "default_priority_code",
        "default_urgency_code",
        "active",
        "sort_order",
        "department_name",
        "issue_type_code",
        "issue_type_name",
    )
    readonly_fields = ("department_name", "issue_type_code", "issue_type_name")
    inlines = (IssueSubcategoryInline, IssueCategoryKeywordInline)

    def changelist_view(
        self, request: HttpRequest, extra_context: dict[str, Any] | None = None
    ) -> HttpResponse:
        """Flag legacy metadata that needs an administrator to link it."""
        unlinked = (
            self.get_queryset(request)
            .filter(active=True, issue_type__isnull=True)
            .count()
        )
        if unlinked:
            self.message_user(
                request,
                f"{unlinked} active chat "
                f"{'category needs' if unlinked == 1 else 'categories need'} "
                "a shared issue type. Filter by empty issue type to reconcile them.",
                level=messages.WARNING,
            )
        return super().changelist_view(request, extra_context)


@admin.register(SlaPolicy)
class SlaPolicyAdmin(admin.ModelAdmin):
    """Admin configuration for public report service targets."""

    list_display = (
        "priority_code",
        "acknowledgement_hours",
        "resolution_working_days",
        "active",
    )
    list_editable = (
        "acknowledgement_hours",
        "resolution_working_days",
        "active",
    )


@admin.register(Reporter)
class ReporterAdmin(admin.ModelAdmin):
    """Admin configuration for reporter contact details."""

    list_display = ("name", "email", "telephone")
    search_fields = ("name", "email", "telephone")


@admin.register(ReportSubmission)
class ReportSubmissionAdmin(admin.ModelAdmin):
    """Admin configuration for report submissions."""

    list_display = (
        "id",
        "work_item",
        "reporter",
        "contact_method",
        "updates_requested",
        "submitted_at",
    )
    list_filter = ("contact_method", "updates_requested", "submitted_at")
    search_fields = ("description", "reporter__name", "reporter__email")
    readonly_fields = (
        "work_item",
        "reported_issue_type",
        "reported_issue_path",
        "other_selected",
        "location_description",
        "reported_impact",
        "reported_time_sensitivity",
        "reported_sensitive_content",
        "latitude",
        "longitude",
        "triage_state",
        "urgent_review",
        "submitted_at",
    )


@admin.register(ReportSubmissionPhoto)
class ReportSubmissionPhotoAdmin(admin.ModelAdmin):
    """Admin configuration for report photos."""

    list_display = ("report_submission", "image_url", "uploaded_at")
    readonly_fields = ("uploaded_at",)


@admin.register(TriageAttempt)
class TriageAttemptAdmin(admin.ModelAdmin):
    """Expose triage history as read-only in the admin."""

    list_display = ("submission", "stage", "reviewer", "decision", "created_at")
    list_filter = ("stage", "created_at")
    readonly_fields = (
        "submission",
        "stage",
        "policy_version",
        "field_outcomes",
        "evidence",
        "decision",
        "reason",
        "reviewer",
        "created_at",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Keep history creation tied to triage operations."""
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: TriageAttempt | None = None
    ) -> bool:
        """Prevent changes to recorded triage attempts."""
        return False

    def has_delete_permission(
        self, request: HttpRequest, obj: TriageAttempt | None = None
    ) -> bool:
        """Prevent deletion of recorded triage attempts."""
        return False


class DraftPolicyInline(admin.TabularInline):
    """Allow policy definition edits on drafts only."""

    extra = 0

    def has_add_permission(
        self, request: HttpRequest, obj: TriagePolicy | None = None
    ) -> bool:
        """Do not add rules to an activated policy."""
        return (
            obj is None or obj.status == TriagePolicy.Status.DRAFT
        ) and super().has_add_permission(request, obj)

    def has_change_permission(
        self, request: HttpRequest, obj: TriagePolicy | None = None
    ) -> bool:
        """Do not change rules on an activated policy."""
        return (
            obj is None or obj.status == TriagePolicy.Status.DRAFT
        ) and super().has_change_permission(request, obj)

    def has_delete_permission(
        self, request: HttpRequest, obj: TriagePolicy | None = None
    ) -> bool:
        """Do not remove rules from an activated policy."""
        return (
            obj is None or obj.status == TriagePolicy.Status.DRAFT
        ) and super().has_delete_permission(request, obj)


class TriagePolicyRuleInline(DraftPolicyInline):
    """Edit a draft's bounded evidence rules."""

    model = TriagePolicyRule


class TriagePolicyScenarioInline(DraftPolicyInline):
    """Edit a draft's expected policy examples."""

    model = TriagePolicyScenario


@admin.register(TriagePolicy)
class TriagePolicyAdmin(admin.ModelAdmin):
    """Prepare drafts without permitting activation through the admin form."""

    list_display = ("name", "version", "status", "activated_at")
    inlines = (TriagePolicyRuleInline, TriagePolicyScenarioInline)
    actions = ("check_scenarios", "summarize_shadow")
    readonly_fields = ("status", "created_at", "activated_at", "activated_by")
    change_form_template = "admin/intake/triagepolicy/change_form.html"

    def get_urls(self) -> list[Any]:
        """Add an explicitly authorized activation confirmation."""
        return [
            path(
                "<int:object_id>/activate/",
                self.admin_site.admin_view(self.activate_view),
                name="intake_triagepolicy_activate",
            ),
            *super().get_urls(),
        ]

    @method_decorator(never_cache)
    def activate_view(self, request: HttpRequest, object_id: int) -> HttpResponse:
        """Require a separately authorized employee to approve a draft."""
        policy = get_object_or_404(TriagePolicy, pk=object_id)
        if not request.user.has_perm(
            "intake.activate_triagepolicy"
        ) or not self.has_view_permission(request, policy):
            raise PermissionDenied
        user_id = request.user.pk
        if user_id is None:
            raise PermissionDenied
        reviewer = Employee.objects.filter(user_id=user_id).first()
        if reviewer is None:
            raise PermissionDenied
        form = PolicyApprovalForm(request.POST if request.method == "POST" else None)
        if request.method == "POST" and form.is_valid():
            try:
                activate_policy(policy.pk, approver=reviewer)
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(
                    request, f"{policy} activated for proposals and review."
                )
                return redirect(
                    reverse("admin:intake_triagepolicy_change", args=[policy.pk])
                )
        try:
            results = evaluate_scenarios(policy)
        except ValidationError:
            results = None
        context = {
            **self.admin_site.each_context(request),
            "title": f"Approve {policy}",
            "policy": policy,
            "form": form,
            "results": results,
            "opts": self.model._meta,
        }
        return render(request, "admin/intake/triagepolicy/activate.html", context)

    def get_readonly_fields(
        self, request: HttpRequest, obj: TriagePolicy | None = None
    ) -> tuple[str, ...]:
        """Keep activated policy details read-only."""
        if obj is not None and obj.status != TriagePolicy.Status.DRAFT:
            return (
                *self.readonly_fields,
                "version",
                "name",
                "service_area",
                "evidence_labels",
                "urgent_review_phrases",
                "duplicate_distance_m",
                "duplicate_age_days",
            )
        return self.readonly_fields

    def has_delete_permission(
        self, request: HttpRequest, obj: TriagePolicy | None = None
    ) -> bool:
        """Keep policy versions available for audit."""
        return False

    def has_change_permission(
        self, request: HttpRequest, obj: TriagePolicy | None = None
    ) -> bool:
        """Only draft policies can be edited in the admin."""
        return (
            obj is None or obj.status == TriagePolicy.Status.DRAFT
        ) and super().has_change_permission(request, obj)

    @admin.action(description="Check policy examples", permissions=["change"])
    def check_scenarios(
        self, request: HttpRequest, queryset: QuerySet[TriagePolicy]
    ) -> None:
        """Report example mismatches without activating the policy."""
        for policy in queryset:
            try:
                results = evaluate_scenarios(policy)
            except ValidationError:
                self.message_user(
                    request,
                    f"{policy}: add valid rules and examples before checking.",
                    messages.ERROR,
                )
                continue
            failed = [result.name for result in results if not result.passed]
            if failed:
                self.message_user(
                    request,
                    f"{policy}: examples requiring attention: {', '.join(failed)}.",
                    messages.WARNING,
                )
            else:
                self.message_user(
                    request,
                    f"{policy}: all {len(results)} examples matched; "
                    "no policy was activated.",
                    messages.SUCCESS,
                )

    @admin.action(description="Summarize shadow results", permissions=["view"])
    def summarize_shadow(
        self, request: HttpRequest, queryset: QuerySet[TriagePolicy]
    ) -> None:
        """Report observed counts without approving or enabling automation."""
        for policy in queryset:
            summary = summarize_pilot(str(policy.version))
            self.message_user(
                request,
                (
                    f"{policy}: reports with proposals: {summary.proposals}; "
                    f"accepted by a reviewer: {summary.reviewed_acceptances}. "
                    f"Priority: {summary.priority.determined} determined, "
                    f"{summary.priority.ambiguous} ambiguous, "
                    f"{summary.priority.conflicting} conflicting, "
                    f"{summary.priority.agreed} agreed, "
                    f"{summary.priority.disagreed} disagreed, "
                    f"{summary.priority.high_risk_missed} missed critical, "
                    f"{summary.priority.high_risk_undetermined} "
                    "undetermined critical. "
                    f"Urgency: {summary.urgency.determined} determined, "
                    f"{summary.urgency.ambiguous} ambiguous, "
                    f"{summary.urgency.conflicting} conflicting, "
                    f"{summary.urgency.agreed} agreed, "
                    f"{summary.urgency.disagreed} disagreed, "
                    f"{summary.urgency.high_risk_missed} missed emergency, "
                    f"{summary.urgency.high_risk_undetermined} "
                    "undetermined emergency. "
                    "Agreement counts compare accepted reports only."
                ),
                messages.INFO,
            )
