"""Admin configuration for public reporting models."""

# mypy: disable-error-code=type-arg

from typing import ClassVar

from django.contrib import admin
from django.http import HttpRequest

from intake.models import (
    ContactMethod,
    IssueCategory,
    IssueCategoryKeyword,
    IssueSubcategory,
    Reporter,
    ReportSubmission,
    ReportSubmissionPhoto,
)


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
        "department_name",
        "issue_type_code",
        "active",
        "sort_order",
    )
    list_editable = ("label", "active", "sort_order")
    list_filter = ("active",)
    search_fields = ("code", "label", "department_name", "issue_type_code")
    inlines = (IssueSubcategoryInline, IssueCategoryKeywordInline)


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
    readonly_fields = ("submitted_at",)


@admin.register(ReportSubmissionPhoto)
class ReportSubmissionPhotoAdmin(admin.ModelAdmin):
    """Admin configuration for report photos."""

    list_display = ("report_submission", "image_url", "uploaded_at")
    readonly_fields = ("uploaded_at",)
