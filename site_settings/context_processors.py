"""Template context processors for site-wide settings."""

from typing import TypedDict

from django.http import HttpRequest

from site_settings.models import ThemeSettings
from site_settings.theme import get_resolved_theme, resolve_theme


class ThemeContext(TypedDict):
    """Template variables used to configure the runtime theme."""

    theme_css_vars: dict[str, str]
    site_name: str
    favicon_url: str
    brand_image_url: str
    theme_revision: int


def theme_settings(request: HttpRequest) -> ThemeContext:
    """Expose configured branding and theme tokens to every Django template."""
    settings = ThemeSettings.objects.filter(pk=1).first()
    if settings is None:
        return {
            "site_name": "Project",
            "favicon_url": "",
            "brand_image_url": "",
            "theme_css_vars": resolve_theme(ThemeSettings()).css_variables,
            "theme_revision": 0,
        }

    return {
        "site_name": settings.site_name,
        "favicon_url": settings.favicon.url if settings.favicon else "",
        "brand_image_url": settings.brand_image.url if settings.brand_image else "",
        "theme_css_vars": get_resolved_theme(settings, settings.revision).css_variables,
        "theme_revision": settings.revision,
    }
