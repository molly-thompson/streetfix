"""Forms for public report submission and central staff review."""

from typing import Any
from uuid import UUID

from django import forms
from django.db import transaction

from employees.organisation_models import IssueType
from employees.work_models import Priority, Urgency
from intake.models import ContactMethod, Reporter, ReportSubmission, TriagePolicy
from intake.services.submission import submit_report
from intake.services.triage.labels import EVIDENCE_CHOICES, validate_evidence_labels


class ReportIssueChoiceField(forms.ModelChoiceField):  # type: ignore[type-arg]
    """Distinguish similarly named issues by their category path."""

    labels: dict[int, str]

    def label_from_instance(self, obj: Any) -> str:
        """Use the complete category path in the no-JavaScript form."""
        return self.labels.get(obj.pk, str(obj))


class ReportSubmissionForm(forms.Form):
    """Collect report evidence without requiring contact details."""

    reported_issue_type = ReportIssueChoiceField(
        queryset=IssueType.objects.none(),
        required=False,
        label="What is the issue about?",
        empty_label="Choose a category or issue",
    )
    other_selected = forms.BooleanField(
        required=False,
        label="The issue is not listed",
    )
    description = forms.CharField(
        label="Describe the issue",
        max_length=5000,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    location_description = forms.CharField(
        required=False,
        label="Describe the location",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    latitude = forms.DecimalField(
        required=False, min_value=-90, max_value=90, max_digits=9, decimal_places=6
    )
    longitude = forms.DecimalField(
        required=False, min_value=-180, max_value=180, max_digits=9, decimal_places=6
    )
    reported_impact = forms.ChoiceField(
        required=False,
        choices=ReportSubmission.ReportedImpact.choices,
        label="How much impact does the issue have?",
    )
    reported_time_sensitivity = forms.ChoiceField(
        required=False,
        choices=ReportSubmission.ReportedTimeSensitivity.choices,
        label="How quickly does the issue need attention?",
    )
    reported_sensitive_content = forms.ChoiceField(
        required=False,
        choices=ReportSubmission.ReportedSensitiveContent.choices,
        label="Does the issue include sensitive or offensive content?",
    )
    updates_requested = forms.BooleanField(required=False, label="I would like updates")
    contact_method = forms.ModelChoiceField(
        queryset=ContactMethod.objects.none(),
        required=False,
        empty_label="Choose a contact method",
    )
    name = forms.CharField(required=False, max_length=150)
    email = forms.EmailField(required=False, max_length=254)
    telephone = forms.CharField(required=False, max_length=40)
    address = forms.CharField(
        required=False, max_length=500, widget=forms.Textarea(attrs={"rows": 2})
    )
    photo_draft = forms.UUIDField(required=False, widget=forms.HiddenInput)
    photo_slots = forms.CharField(
        required=False, max_length=300, widget=forms.HiddenInput
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """Load the available categories and contact methods."""
        super().__init__(*args, **kwargs)
        issue_field = self.fields["reported_issue_type"]
        method_field = self.fields["contact_method"]
        assert isinstance(issue_field, ReportIssueChoiceField)  # noqa: S101
        assert isinstance(method_field, forms.ModelChoiceField)  # noqa: S101
        issue_field.queryset = IssueType.objects.filter(active=True).select_related(
            "parent", "department"
        )
        issues = list(issue_field.queryset)
        by_id = {issue.pk: issue for issue in issues}
        issue_field.labels = {}
        for issue in issues:
            path = []
            seen = set()
            current: IssueType | None = issue
            while current is not None and current.pk not in seen:
                seen.add(current.pk)
                path.append(current.name)
                current = by_id.get(current.parent_id) if current.parent_id else None
            issue_field.labels[issue.pk] = " / ".join(reversed(path))
        method_field.queryset = ContactMethod.objects.all()
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs["class"] = "uk-checkbox"
            elif isinstance(widget, forms.Select):
                widget.attrs["class"] = "uk-select"
            elif isinstance(widget, forms.Textarea):
                widget.attrs["class"] = "uk-textarea"
            else:
                widget.attrs["class"] = "uk-input"
        policy = TriagePolicy.objects.filter(status=TriagePolicy.Status.ACTIVE).first()
        if policy is not None:
            try:
                configured = validate_evidence_labels(policy.evidence_labels)
            except forms.ValidationError:
                configured = {}
            for name, config in configured.items():
                field = self.fields[name]
                field.label = config.get("label", field.label)
                field.help_text = config.get("guidance", field.help_text)
                assert isinstance(field, forms.ChoiceField)  # noqa: S101
                labels = config.get("choices", {})
                field.choices = [
                    (code, labels.get(code, label))
                    for code, label in EVIDENCE_CHOICES[name]
                ]

    def clean(self) -> dict[str, Any]:
        """Check paired location and update details."""
        cleaned = super().clean() or {}
        selected = cleaned.get("reported_issue_type")
        other = cleaned.get("other_selected")
        if selected is None and not other:
            self.add_error("reported_issue_type", "Choose an issue or select Other.")
        elif selected is not None:
            if other and selected.kind != IssueType.Kind.CATEGORY:
                self.add_error("reported_issue_type", "Select Other under a category.")
            elif not other and selected.kind != IssueType.Kind.ISSUE:
                self.add_error(
                    "reported_issue_type", "Choose an issue or select Other."
                )
        sensitive = cleaned.get("reported_sensitive_content")
        if sensitive not in (
            "",
            None,
            ReportSubmission.ReportedSensitiveContent.UNKNOWN,
        ):
            if selected is None or not selected.sensitive_content_enabled:
                self.add_error(
                    "reported_sensitive_content",
                    "This question is not enabled for the selected issue.",
                )
        if (cleaned.get("latitude") is None) != (cleaned.get("longitude") is None):
            raise forms.ValidationError("Provide both coordinates or leave both blank.")
        slots = [part for part in cleaned.get("photo_slots", "").split(",") if part]
        try:
            cleaned["photo_slot_ids"] = [UUID(part) for part in slots]
        except ValueError:
            self.add_error("photo_slots", "A photo reference was not recognised.")
        else:
            if cleaned["photo_slot_ids"] and cleaned.get("photo_draft") is None:
                self.add_error("photo_slots", "A photo upload draft is required.")
        if cleaned.get("updates_requested"):
            method = cleaned.get("contact_method")
            fields = {"EMAIL": "email", "TELEPHONE": "telephone", "POST": "address"}
            field_name = fields.get(method.code) if method is not None else None
            if field_name is None:
                self.add_error("contact_method", "Choose how to receive updates.")
            elif not cleaned.get(field_name, "").strip():
                self.add_error(field_name, "Provide this detail to receive updates.")
        return cleaned

    @transaction.atomic
    def save(self, *, session_key: str = "") -> ReportSubmission:
        """Save the report, its contact details and any photos together."""
        if not self.is_valid():
            raise ValueError("The report form must be valid before saving.")
        data = self.cleaned_data
        contact_details = {
            field: data.get(field, "")
            for field in ("name", "email", "telephone", "address")
        }
        reporter = (
            Reporter.objects.create(**contact_details)
            if any(contact_details.values())
            else None
        )
        submission = ReportSubmission(
            reporter=reporter,
            contact_method=data.get("contact_method"),
            updates_requested=data["updates_requested"],
            reported_issue_type=data.get("reported_issue_type"),
            other_selected=data["other_selected"],
            description=data["description"],
            location_description=data["location_description"],
            latitude=data.get("latitude"),
            longitude=data.get("longitude"),
            reported_impact=data.get("reported_impact")
            or ReportSubmission.ReportedImpact.UNKNOWN,
            reported_time_sensitivity=data.get("reported_time_sensitivity")
            or ReportSubmission.ReportedTimeSensitivity.UNKNOWN,
            reported_sensitive_content=data.get("reported_sensitive_content")
            or ReportSubmission.ReportedSensitiveContent.UNKNOWN,
        )
        return submit_report(
            submission,
            photo_draft_id=data.get("photo_draft"),
            photo_slot_ids=data.get("photo_slot_ids", []),
            session_key=session_key,
        )


class LocationCorrectionForm(forms.Form):
    """Capture a reviewer's corrected coordinates and explanation."""

    latitude = forms.DecimalField(
        min_value=-90,
        max_value=90,
        max_digits=9,
        decimal_places=6,
        widget=forms.NumberInput(attrs={"class": "uk-input"}),
    )
    longitude = forms.DecimalField(
        min_value=-180,
        max_value=180,
        max_digits=9,
        decimal_places=6,
        widget=forms.NumberInput(attrs={"class": "uk-input"}),
    )
    reason = forms.CharField(
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2, "class": "uk-textarea"}),
    )


class OutOfScopeForm(forms.Form):
    """Capture a reviewer's reason for rejecting a report."""

    reason = forms.CharField(
        label="Why is this report out of scope?",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "class": "uk-textarea"}),
    )


class ReopenReportForm(forms.Form):
    """Capture the reason for correcting a final triage decision."""

    reason = forms.CharField(
        label="Why does this report need another review?",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "class": "uk-textarea"}),
    )


class DuplicateLookupForm(forms.Form):
    """Look up a specific work item for duplicate review."""

    work_item_id = forms.IntegerField(
        label="Work item number",
        min_value=1,
        max_value=9223372036854775807,
        widget=forms.NumberInput(attrs={"class": "uk-input"}),
    )


class DuplicateConfirmationForm(forms.Form):
    """Capture a duplicate decision and its explanation."""

    work_item_id = forms.IntegerField(
        min_value=1, max_value=9223372036854775807, widget=forms.HiddenInput
    )
    reason = forms.CharField(
        label="Why is this the same issue?",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "class": "uk-textarea"}),
    )
    confirmed_not_recurrence = forms.BooleanField(
        required=False,
        label=(
            "For resolved work, I confirmed this is the same issue, not a recurrence."
        ),
        widget=forms.CheckboxInput(attrs={"class": "uk-checkbox"}),
    )


class RoutableIssueChoiceField(forms.ModelChoiceField):  # type: ignore[type-arg]
    """Display the department responsible for each issue type."""

    def label_from_instance(self, obj: Any) -> str:
        """Include the department in the issue choice."""
        return f"{obj} ({obj.department})"


class AcceptReportForm(forms.Form):
    """Capture human decisions required to create operational work."""

    issue_type = RoutableIssueChoiceField(
        queryset=IssueType.objects.none(),
        label="Issue type and responsible department",
        widget=forms.Select(attrs={"class": "uk-select"}),
    )
    priority = forms.ModelChoiceField(
        queryset=Priority.objects.none(),
        empty_label="Choose priority",
        widget=forms.Select(attrs={"class": "uk-select"}),
    )
    urgency = forms.ModelChoiceField(
        queryset=Urgency.objects.none(),
        empty_label="Choose urgency",
        widget=forms.Select(attrs={"class": "uk-select"}),
    )
    scope_confirmed = forms.BooleanField(
        label="I confirmed this issue is within our responsibility.",
        widget=forms.CheckboxInput(attrs={"class": "uk-checkbox"}),
    )
    not_duplicate_confirmed = forms.BooleanField(
        label="I checked for existing work and confirmed this needs a new work item.",
        widget=forms.CheckboxInput(attrs={"class": "uk-checkbox"}),
    )
    location_confirmed = forms.BooleanField(
        label="I confirmed the map pin is reliable.",
        widget=forms.CheckboxInput(attrs={"class": "uk-checkbox"}),
    )
    reason = forms.CharField(
        label="Reason for these decisions",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3, "class": "uk-textarea"}),
    )

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        """List only routable issue types and fixed work outcomes."""
        super().__init__(*args, **kwargs)
        issue = self.fields["issue_type"]
        priority = self.fields["priority"]
        urgency = self.fields["urgency"]
        assert isinstance(issue, forms.ModelChoiceField)  # noqa: S101
        assert isinstance(priority, forms.ModelChoiceField)  # noqa: S101
        assert isinstance(urgency, forms.ModelChoiceField)  # noqa: S101
        issue.queryset = IssueType.objects.filter(
            kind=IssueType.Kind.ISSUE, department__isnull=False
        ).select_related("department")
        priority.queryset = Priority.objects.filter(
            code__in=("LOW", "NORMAL", "HIGH", "CRITICAL")
        )
        urgency.queryset = Urgency.objects.filter(
            code__in=("ROUTINE", "SOON", "URGENT", "EMERGENCY")
        )


class PolicyApprovalForm(forms.Form):
    """Record an approver's explicit policy review."""

    confirmed = forms.BooleanField(
        label="I reviewed the policy and its examples and approve this version."
    )
