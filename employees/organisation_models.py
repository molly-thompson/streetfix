"""Organisation and employee models."""

from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q


class Department(models.Model):
    """An organisation unit responsible for work items."""

    name = models.CharField(max_length=150, unique=True)

    def __str__(self) -> str:
        """Return the department name."""
        return self.name


class IssueType(models.Model):
    """A category or a routable kind of issue."""

    class Kind(models.TextChoices):
        """Distinguish grouping categories from routable issue types."""

        CATEGORY = "CATEGORY", "Category"
        ISSUE = "ISSUE", "Issue type"

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="issue_types",
        null=True,
        blank=True,
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        related_name="children",
        null=True,
        blank=True,
    )
    kind = models.CharField(max_length=10, choices=Kind, default=Kind.ISSUE)
    sensitive_content_enabled = models.BooleanField(default=False)
    active = models.BooleanField(
        default=True,
        help_text="Offer this option to people reporting a problem.",
    )
    sort_order = models.PositiveIntegerField(default=0)
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=40)

    class Meta:
        """Order issue types by department and name."""

        constraints = [
            models.UniqueConstraint(
                fields=("department", "name"),
                name="unique_issue_type_name_per_department",
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind="CATEGORY", department__isnull=True)
                    | Q(kind="ISSUE", department__isnull=False)
                ),
                name="issue_type_kind_department_consistent",
            ),
            models.CheckConstraint(
                condition=Q(kind="ISSUE") | Q(sensitive_content_enabled=False),
                name="sensitive_content_only_for_issue_type",
            ),
        ]
        ordering = ("department__name", "name")

    def __str__(self) -> str:
        """Return the issue type name."""
        return self.name

    def clean(self) -> None:
        """Keep categories, routing, and the hierarchy consistent."""
        super().clean()
        errors: dict[str, str] = {}
        if self.kind == self.Kind.CATEGORY and self.department_id:
            errors["department"] = "Categories do not have a department."
        elif self.kind == self.Kind.ISSUE and not self.department_id:
            errors["department"] = "A routable issue type needs a department."
        if self.kind == self.Kind.CATEGORY and self.sensitive_content_enabled:
            errors["sensitive_content_enabled"] = (
                "Sensitive-content evidence is enabled on issue types, not categories."
            )

        if self.parent_id:
            parent = self.parent
            if parent is not None and parent.kind != self.Kind.CATEGORY:
                errors["parent"] = "Only categories can contain issue types."
            visited: set[int] = set()
            while parent is not None:
                if parent.pk == self.pk or parent.pk in visited:
                    errors["parent"] = "The issue hierarchy cannot contain a cycle."
                    break
                visited.add(parent.pk)
                parent = parent.parent if parent.parent_id else None

        if self.pk and self.kind == self.Kind.ISSUE and self.children.exists():
            errors["kind"] = "A category with children cannot become an issue type."
        if self.pk and self.kind == self.Kind.CATEGORY and self.work_items.exists():
            errors["kind"] = "An issue type with work items cannot become a category."

        if errors:
            raise ValidationError(errors)


class Employee(models.Model):
    """An employee profile linked to a Django authentication user."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employee_profile",
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="employees",
    )
    manager = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        related_name="direct_reports",
        null=True,
        blank=True,
    )
    email = models.EmailField(max_length=254, unique=True, null=True, blank=True)
    name = models.CharField(max_length=150)

    class Meta:
        """Order employees by display name."""

        ordering = ("name",)

    def __str__(self) -> str:
        """Return the attribution name."""
        return self.name

    @transaction.atomic
    def deactivate_and_anonymize(self) -> None:
        """Deactivate login and clear contact details while retaining attribution."""
        employee = (
            Employee.objects.select_for_update().select_related("user").get(pk=self.pk)
        )
        employee.email = None
        employee.save(update_fields=("email",))

        user = employee.user
        user.is_active = False
        user.email = ""
        user.first_name = ""
        user.last_name = ""
        user.username = f"offboarded-{uuid4().hex}"
        user.set_unusable_password()
        user.save(
            update_fields=(
                "email",
                "first_name",
                "last_name",
                "username",
                "password",
                "is_active",
            )
        )

        self.email = None
