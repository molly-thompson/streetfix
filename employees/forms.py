"""Forms for the employees application."""

from typing import Any

from django import forms

from .organisation_models import Employee
from .work_models import WorkItem


class AssignWorkForm(forms.Form):
    """Choose who to put on a work item and in what role."""

    ROLE_CHOICES = (
        ("case_officer", "Case officer (responsible for the job)"),
        ("support", "Support"),
    )

    employee = forms.ModelChoiceField(
        queryset=Employee.objects.none(),
        empty_label="Choose an employee",
    )
    role = forms.ChoiceField(
        choices=ROLE_CHOICES,
        initial="case_officer",
        widget=forms.RadioSelect,
    )
    reason = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.TextInput(attrs={"placeholder": "Optional, e.g. Priya off sick"}),
    )

    def __init__(self, *args: Any, work_item: WorkItem, **kwargs: Any) -> None:
        """Limit choices to active employees in the responsible department."""
        super().__init__(*args, **kwargs)
        employee_field = self.fields["employee"]
        assert isinstance(employee_field, forms.ModelChoiceField)  # noqa: S101
        department_id = work_item.issue_type.department_id
        if department_id is not None:
            employee_field.queryset = Employee.objects.filter(
                department_id=department_id,
                user__is_active=True,
            )

    @property
    def as_case_officer(self) -> bool:
        """Return whether the chosen role is case officer."""
        return bool(self.cleaned_data["role"] == "case_officer")


class RemoveFromWorkForm(forms.Form):
    """Take someone off a work item, with an optional reason."""

    assignment = forms.IntegerField(widget=forms.HiddenInput)
    reason = forms.CharField(required=False, max_length=500)


class PhotoField(forms.FileField):
    """An uploaded photo from the phone's camera or gallery."""

    def __init__(self, **kwargs: Any) -> None:
        """Ask phones to open the camera."""
        kwargs.setdefault("required", False)
        kwargs.setdefault(
            "widget",
            forms.ClearableFileInput(
                attrs={"accept": "image/*", "capture": "environment"}
            ),
        )
        super().__init__(**kwargs)

    def clean(self, data: Any, initial: Any = None) -> Any:
        """Accept image files only."""
        image = super().clean(data, initial)
        content_type = getattr(image, "content_type", "") or ""
        if image and not content_type.startswith("image/"):
            raise forms.ValidationError("Upload a photo (an image file).")
        return image


class BeforePhotoForm(forms.Form):
    """A before photo, or the reason one could not be taken."""

    photo = PhotoField()
    no_photo_reason = forms.CharField(required=False, max_length=1000)


class CommentForm(forms.Form):
    """A comment from the officer to their manager."""

    content = forms.CharField(
        max_length=2000,
        widget=forms.Textarea(
            attrs={
                "aria-label": "Comment",
                "data-dictate": True,
                "placeholder": "Write a comment…",
                "rows": 5,
            }
        ),
    )
