"""Admin configuration for employee and work models."""

# mypy: disable-error-code=type-arg

from typing import ClassVar

from django.contrib import admin
from django.db import models, transaction
from django.db.models import QuerySet
from django.forms import ModelForm
from django.http import HttpRequest

from .organisation_models import Department, Employee, IssueType
from .work_models import (
    CancellationReason,
    PhotoTag,
    Priority,
    Urgency,
    VisitOutcome,
    VisitReportOption,
    WorkAssignment,
    WorkItem,
    WorkItemComment,
    WorkItemPhoto,
    WorkItemReport,
    WorkItemStatus,
    WorkItemStatusHistory,
    WorkStatusTransition,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    """Admin configuration for departments."""

    list_display = ("name",)
    search_fields = ("name",)


@admin.register(IssueType)
class IssueTypeAdmin(admin.ModelAdmin):
    """Admin configuration for department issue types."""

    list_display = ("name", "code", "department")
    list_filter = ("department",)
    search_fields = ("name", "code", "department__name")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    """Admin configuration for employee profiles."""

    list_display = ("name", "email", "department", "manager", "user")
    list_filter = ("department",)
    search_fields = ("name", "email", "user__username", "user__email")
    actions = ("deactivate_and_anonymize",)

    @admin.action(description="Deactivate and anonymize selected employees")
    def deactivate_and_anonymize(
        self,
        request: HttpRequest,
        queryset: QuerySet[Employee],
    ) -> None:
        """Deactivate selected accounts and clear their contact details."""
        for employee in queryset:
            employee.deactivate_and_anonymize()

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: Employee | None = None,
    ) -> bool:
        """Keep employee records for attribution."""
        return False


class FixedOptionAdmin(admin.ModelAdmin):
    """Allow label edits while keeping seeded option codes fixed."""

    list_display: ClassVar[tuple[str, ...]] = (  # type: ignore[misc]
        "code",
        "label",
        "active",
        "sort_order",
    )
    list_editable: ClassVar[tuple[str, ...]] = (
        "label",
        "active",
        "sort_order",
    )
    ordering = ("code",)
    readonly_fields: ClassVar[tuple[str, ...]] = ("code",)

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Prevent creation of option values outside the seed migration."""
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
    ) -> bool:
        """Prevent deletion of fixed option values."""
        return False


@admin.register(Priority)
class PriorityAdmin(FixedOptionAdmin):
    """Admin configuration for priority labels."""

    readonly_fields: ClassVar[tuple[str, ...]] = ("code", "guidance")
    list_editable: ClassVar[tuple[str, ...]] = (
        "label",
        "rank",
        "is_urgent",
        "style_key",
        "color",
        "active",
        "sort_order",
    )
    list_display: ClassVar[tuple[str, ...]] = (  # type: ignore[misc]
        "code",
        "label",
        "rank",
        "is_urgent",
        "style_key",
        "color",
        "active",
        "sort_order",
    )


@admin.register(Urgency)
class UrgencyAdmin(FixedOptionAdmin):
    """Admin configuration for urgency labels."""

    readonly_fields: ClassVar[tuple[str, ...]] = ("code", "guidance")
    list_editable: ClassVar[tuple[str, ...]] = (
        "label",
        "rank",
        "is_emergency",
        "style_key",
        "active",
        "sort_order",
    )
    list_display: ClassVar[tuple[str, ...]] = (  # type: ignore[misc]
        "code",
        "label",
        "rank",
        "is_emergency",
        "style_key",
        "active",
        "sort_order",
    )


@admin.register(CancellationReason)
class CancellationReasonAdmin(FixedOptionAdmin):
    """Admin configuration for cancellation reason policies."""

    list_display: ClassVar[tuple[str, ...]] = (  # type: ignore[misc]
        "code",
        "label",
        "notes_required",
        "active",
        "sort_order",
    )
    list_editable: ClassVar[tuple[str, ...]] = (
        "label",
        "notes_required",
        "active",
        "sort_order",
    )


@admin.register(VisitOutcome)
class VisitOutcomeAdmin(FixedOptionAdmin):
    """Admin configuration for visit outcome transitions."""

    list_display: ClassVar[tuple[str, ...]] = (  # type: ignore[misc]
        "code",
        "label",
        "target_status_code",
        "further_work_required",
        "unfinished",
        "active",
        "sort_order",
    )
    list_editable: ClassVar[tuple[str, ...]] = (
        "label",
        "target_status_code",
        "further_work_required",
        "unfinished",
        "active",
        "sort_order",
    )


@admin.register(PhotoTag)
class PhotoTagAdmin(FixedOptionAdmin):
    """Admin configuration for visit photo stages."""


@admin.register(VisitReportOption)
class VisitReportOptionAdmin(admin.ModelAdmin):
    """Admin configuration for dynamic visit-report options."""

    list_display = ("option_type", "code", "label", "active", "sort_order")
    list_editable = ("label", "active", "sort_order")
    list_filter = ("option_type", "active")


@admin.register(WorkItemStatus)
class WorkItemStatusAdmin(FixedOptionAdmin):
    """Admin configuration for lifecycle status semantics."""

    list_display: ClassVar[tuple[str, ...]] = (  # type: ignore[misc]
        "code",
        "label",
        "rank",
        "is_not_yet_triaged",
        "is_triaged",
        "is_assigned",
        "is_officer_active",
        "is_paused",
        "is_awaiting_review",
        "is_resolved",
        "is_ended",
        "is_cancelled",
        "style_key",
        "active",
        "sort_order",
    )
    list_editable: ClassVar[tuple[str, ...]] = (
        "label",
        "rank",
        "is_not_yet_triaged",
        "is_triaged",
        "is_assigned",
        "is_officer_active",
        "is_paused",
        "is_awaiting_review",
        "is_resolved",
        "is_ended",
        "is_cancelled",
        "style_key",
        "active",
        "sort_order",
    )


@admin.register(WorkStatusTransition)
class WorkStatusTransitionAdmin(admin.ModelAdmin):
    """Admin configuration for allowed lifecycle transitions."""

    list_display: ClassVar[tuple[str, ...]] = (  # type: ignore[misc]
        "source_status",
        "target_status",
        "action_code",
        "active",
    )
    list_editable: ClassVar[tuple[str, ...]] = ("action_code", "active")
    list_filter = ("active", "source_status", "target_status")


@admin.register(WorkItem)
class WorkItemAdmin(admin.ModelAdmin):
    """Admin configuration that records status changes in history."""

    list_display = ("id", "issue_type", "priority", "urgency", "status", "created_at")
    list_filter = ("status", "priority", "urgency", "issue_type__department")
    search_fields = ("issue_type__name", "issue_type__code")
    readonly_fields = ("created_at", "ended_at")

    @transaction.atomic
    def save_model(
        self,
        request: HttpRequest,
        obj: WorkItem,
        form: ModelForm[WorkItem],
        change: bool,
    ) -> None:
        """Record admin status edits through the transition operation."""
        if not change:
            super().save_model(request, obj, form, change)
            return

        current = WorkItem.objects.select_related("status").get(pk=obj.pk)
        if current.status_id == obj.status_id:
            super().save_model(request, obj, form, change)
            return

        target_status = obj.status
        cancellation_reason = obj.cancellation_reason
        cancellation_notes = obj.cancellation_notes
        employee = None
        if request.user.is_authenticated and request.user.pk is not None:
            employee = Employee.objects.filter(user_id=request.user.pk).first()
        current.transition_to(
            target_status,
            changed_by=employee,
            cancellation_reason=cancellation_reason,
            cancellation_notes=cancellation_notes,
        )

        transition_fields = {
            "status",
            "ended_at",
            "cancellation_reason",
            "cancellation_notes",
            "cancelled_by",
            "created_at",
            "id",
        }
        for field in obj._meta.concrete_fields:
            if field.name not in transition_fields:
                setattr(current, field.name, getattr(obj, field.name))
        current.save()
        obj.refresh_from_db()


@admin.register(WorkItemStatusHistory)
class WorkItemStatusHistoryAdmin(admin.ModelAdmin):
    """Read-only status history in the admin."""

    list_display = (
        "work_item",
        "previous_status",
        "new_status",
        "changed_by",
        "changed_at",
    )
    list_filter = ("new_status", "changed_at")
    readonly_fields = (
        "work_item",
        "changed_by",
        "previous_status",
        "new_status",
        "changed_at",
        "notes",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Keep history creation tied to status transitions."""
        return False

    def has_change_permission(
        self,
        request: HttpRequest,
        obj: WorkItemStatusHistory | None = None,
    ) -> bool:
        """Keep recorded status transitions immutable."""
        return False


@admin.register(WorkItemComment)
class WorkItemCommentAdmin(admin.ModelAdmin):
    """Admin configuration for internal comments."""

    list_display = ("work_item", "author", "created_at")
    list_filter = ("created_at",)
    search_fields = ("content", "author__name")


@admin.register(WorkAssignment)
class WorkAssignmentAdmin(admin.ModelAdmin):
    """Assignment history in the admin; changes go through ``assign``."""

    list_display = (
        "work_item",
        "employee",
        "is_case_officer",
        "assigned_by",
        "assigned_at",
        "unassigned_at",
    )
    list_filter = ("is_case_officer", "employee__department", "assigned_at")
    search_fields = ("employee__name", "reason")
    readonly_fields = (
        "work_item",
        "employee",
        "is_case_officer",
        "assigned_by",
        "assigned_at",
        "unassigned_at",
        "reason",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Keep assignment creation tied to the assign operation."""
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: WorkAssignment | None = None,
    ) -> bool:
        """Keep assignment history for attribution."""
        return False


class WorkItemPhotoInline(admin.TabularInline):
    """Read-only photos shown on their report."""

    model = WorkItemPhoto
    extra = 0
    can_delete = False
    readonly_fields = ("tag", "image_url", "uploaded_by", "taken_at")

    def has_add_permission(
        self,
        request: HttpRequest,
        obj: models.Model | None = None,
    ) -> bool:
        """Photos come from the field app, not the admin."""
        return False


@admin.register(WorkItemReport)
class WorkItemReportAdmin(admin.ModelAdmin):
    """Read-only visit reports with their photos."""

    list_display = ("work_item", "employee", "outcome", "arrived_at", "submitted_at")
    list_filter = ("outcome", "further_work_needed", "employee__department")
    search_fields = ("employee__name", "findings", "work_done", "additional_notes")
    inlines = (WorkItemPhotoInline,)
    readonly_fields = (
        "work_item",
        "employee",
        "arrived_at",
        "submitted_at",
        "outcome",
        "findings",
        "work_done",
        "materials",
        "further_work_needed",
        "no_before_photo_reason",
        "extra_answers",
        "additional_notes",
        "ai_summary",
    )

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Reports come from the field app, not the admin."""
        return False

    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: WorkItemReport | None = None,
    ) -> bool:
        """Keep visit reports as evidence."""
        return False
