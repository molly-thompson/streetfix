"""Tests for backend-authoritative theme resolution."""

import pytest

from site_settings.models import ThemeSettings
from site_settings.theme import get_resolved_theme, resolve_theme

pytestmark = pytest.mark.django_db


def test_minimal_theme_resolves_complete_output() -> None:
    """Resolve a complete concrete token document from the minimum inputs."""
    resolved = resolve_theme(ThemeSettings())

    assert resolved.colors["primary"] == "#0f6b63"
    assert resolved.colors["background"] == "#f5f6f8"
    assert resolved.colors["surface"] == "#ffffff"
    assert resolved.colors["success_surface"] == "#eaf3ec"
    assert "--theme-font-sans" in resolved.css_variables
    assert "--theme-font-mono" in resolved.css_variables
    assert resolved.css_variables["--theme-font-sans"].startswith("IBM Plex Sans")
    assert not resolved.css_variables["--theme-font-sans"].startswith("&quot")
    assert "--theme-primary-rgb" in resolved.css_variables
    assert all(value for value in resolved.css_variables.values())
    assert not resolved.contrast_errors


def test_explicit_tier_two_values_are_preserved() -> None:
    """Keep intentional high-level overrides in the resolved document."""
    settings = ThemeSettings(
        primary_color="#335c9a",
        on_primary_color="#ffffff",
        primary_hover_color="#244778",
        success_surface_color="#ffffff",
        success_text_color="#166534",
    )

    resolved = resolve_theme(settings)

    assert resolved.colors["primary"] == "#335c9a"
    assert resolved.colors["on_primary"] == "#ffffff"
    assert resolved.colors["primary_hover"] == "#244778"
    assert resolved.colors["success_surface"] == "#ffffff"
    assert resolved.colors["success_text"] == "#166534"


def test_resolved_theme_is_cached_by_revision(
    theme_settings: ThemeSettings,
) -> None:
    """Use deterministic revision keys and refresh after saves."""
    first = get_resolved_theme(theme_settings, theme_settings.revision)
    second = get_resolved_theme(theme_settings, theme_settings.revision)

    assert first == second

    old_revision = theme_settings.revision
    theme_settings.primary_color = "#335c9a"
    theme_settings.primary_text_color = "#335c9a"
    theme_settings.save()

    assert theme_settings.revision == old_revision + 1
    updated = get_resolved_theme(theme_settings, theme_settings.revision)
    assert updated.colors["primary"] == "#335c9a"
