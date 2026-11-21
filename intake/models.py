"""Public reporting and intake models."""

from django.db import models


class ContactMethod(models.Model):
    """A fixed contact method with an administrator-editable label."""

    code = models.CharField(max_length=40, unique=True, editable=False)
    label = models.CharField(max_length=100)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("code",)

    def __str__(self) -> str:
        """Return the configurable label."""
        return self.label


class IssueCategory(models.Model):
    """A public report category and its internal routing configuration."""

    code = models.CharField(max_length=40, unique=True)
    label = models.CharField(max_length=150)
    department_name = models.CharField(max_length=150)
    issue_type_code = models.CharField(max_length=40)
    issue_type_name = models.CharField(max_length=150)
    default_priority_code = models.CharField(max_length=40, blank=True)
    default_urgency_code = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "code")

    def __str__(self) -> str:
        """Return the public category label."""
        return self.label


class IssueSubcategory(models.Model):
    """A category-specific sub-issue option."""

    category = models.ForeignKey(
        IssueCategory,
        on_delete=models.CASCADE,
        related_name="subcategories",
    )
    code = models.CharField(max_length=40)
    label = models.CharField(max_length=150)
    raised_priority_code = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("sort_order", "code")
        constraints = [
            models.UniqueConstraint(
                fields=("category", "code"),
                name="unique_issue_subcategory_per_category",
            )
        ]

    def __str__(self) -> str:
        """Return the subcategory label."""
        return self.label


class IssueCategoryKeyword(models.Model):
    """A rules-based text hint for suggesting an issue category."""

    category = models.ForeignKey(
        IssueCategory,
        on_delete=models.CASCADE,
        related_name="keywords",
    )
    pattern = models.CharField(max_length=300)
    active = models.BooleanField(default=True)

    class Meta:
        ordering = ("category__sort_order", "pk")

    def __str__(self) -> str:
        """Return the keyword rule."""
        return f"{self.category.code}: {self.pattern}"


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
    """A public submission associated with an internal work item."""

    work_item = models.ForeignKey(
        "employees.WorkItem",
        on_delete=models.PROTECT,
        related_name="submissions",
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
    )
    updates_requested = models.BooleanField()
    description = models.TextField()
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-submitted_at",)

    def __str__(self) -> str:
        """Identify the submission and its work item."""
        return f"Submission {self.pk} for work item {self.work_item_id}"


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
