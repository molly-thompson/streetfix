"""Validate bounded labels for reporter-provided triage evidence."""

from typing import Any

from django.core.exceptions import ValidationError

from intake.models import ReportSubmission

EVIDENCE_CHOICES = {
    "reported_impact": ReportSubmission.ReportedImpact.choices,
    "reported_time_sensitivity": ReportSubmission.ReportedTimeSensitivity.choices,
    "reported_sensitive_content": ReportSubmission.ReportedSensitiveContent.choices,
}
EVIDENCE_CODES = {
    field: {code for code, _ in choices} for field, choices in EVIDENCE_CHOICES.items()
}


def validate_evidence_labels(value: Any) -> dict[str, Any]:
    """Validate labels without allowing deployments to redefine evidence codes."""
    if not isinstance(value, dict) or set(value) - EVIDENCE_CODES.keys():
        raise ValidationError("Evidence labels must use the supported evidence fields.")
    for field, config in value.items():
        if not isinstance(config, dict) or set(config) - {
            "label",
            "guidance",
            "choices",
        }:
            raise ValidationError(f"{field} contains unsupported label settings.")
        for key in ("label", "guidance"):
            if key in config and (
                not isinstance(config[key], str)
                or not config[key].strip()
                or len(config[key]) > (200 if key == "label" else 1000)
            ):
                raise ValidationError(f"{field} has an invalid {key}.")
        choices = config.get("choices", {})
        if (
            not isinstance(choices, dict)
            or set(choices) - EVIDENCE_CODES[field]
            or any(
                not isinstance(label, str) or not label.strip() or len(label) > 200
                for label in choices.values()
            )
        ):
            raise ValidationError(f"{field} has invalid choice labels.")
    return value
