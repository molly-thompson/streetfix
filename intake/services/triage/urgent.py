"""Match explicitly configured text cues for urgent human review."""

import re
from typing import Any

from django.core.exceptions import ValidationError


def validate_urgent_phrases(value: Any) -> list[str]:
    """Require a list of bounded, non-empty literal phrases."""
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() or len(item) > 200
        for item in value
    ):
        raise ValidationError(
            "Enter a list of non-empty phrases, each at most 200 characters."
        )
    if len({item.strip().casefold() for item in value}) != len(value):
        raise ValidationError("Urgent-review phrases must be unique.")
    return [item.strip() for item in value]


def matching_urgent_phrases(description: str, phrases: list[str]) -> list[str]:
    """Find literal cues at word boundaries; a match is not an urgency decision."""
    text = description.casefold()
    return [
        phrase
        for phrase in phrases
        if re.search(r"(?<!\w)" + re.escape(phrase.casefold()) + r"(?!\w)", text)
    ]
