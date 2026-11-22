"""Shared presentation helpers for StreetFix interfaces."""

from django import template
from django.templatetags.static import static
from django.utils.html import format_html
from django.utils.safestring import SafeString

register = template.Library()

ICON_NAMES = frozenset(
    {
        "alert-triangle",
        "arrow-left",
        "arrow-right",
        "calendar",
        "camera",
        "check",
        "chevron-down",
        "chevron-left",
        "chevron-right",
        "circle-check",
        "clipboard-check",
        "clock",
        "external-link",
        "file-text",
        "image",
        "info",
        "list",
        "log-out",
        "mail",
        "map",
        "map-pin",
        "menu",
        "navigation",
        "pencil",
        "phone",
        "plus",
        "route",
        "search",
        "upload",
        "user",
        "x",
    }
)


@register.simple_tag
def icon(name: str, label: str = "") -> SafeString:
    """Render an approved SVG symbol."""
    if name not in ICON_NAMES:
        raise ValueError(f"Unknown StreetFix icon: {name}")
    sprite_url = static("icons/streetfix-icons.svg")
    if label:
        return format_html(
            '<svg class="sf-icon" aria-label="{}" role="img" focusable="false">'
            '<use href="{}#{}"></use></svg>',
            label,
            sprite_url,
            name,
        )
    return format_html(
        '<svg class="sf-icon" aria-hidden="true" focusable="false">'
        '<use href="{}#{}"></use></svg>',
        sprite_url,
        name,
    )
