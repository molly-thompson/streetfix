"""Forms for the central staff review of reports."""

from typing import Any

from django import forms

from employees.organisation_models import IssueType
from employees.work_models import Priority, Urgency


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
