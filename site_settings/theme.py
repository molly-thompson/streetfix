"""Backend-authoritative theme resolution and contrast validation."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from coloraide import Color
from django.core.cache import cache

MINIMUM_TEXT_CONTRAST = 4.5


class ThemeSource(Protocol):
    """Fields needed to resolve persisted theme settings."""

    primary_color: str
    background_color: str
    text_color: str
    surface_color: str
    surface_elevated_color: str
    emphasis_text_color: str
    muted_text_color: str
    tertiary_text_color: str
    disabled_text_color: str
    border_color: str
    link_color: str
    link_hover_color: str
    on_primary_color: str
    primary_hover_color: str
    primary_active_color: str
    primary_text_color: str
    primary_surface_color: str
    secondary_color: str
    secondary_text_color: str
    secondary_surface_color: str
    on_secondary_color: str
    success_color: str
    success_text_color: str
    success_surface_color: str
    on_success_color: str
    warning_color: str
    warning_text_color: str
    warning_surface_color: str
    on_warning_color: str
    danger_color: str
    danger_text_color: str
    danger_surface_color: str
    on_danger_color: str
    info_color: str
    info_text_color: str
    info_surface_color: str
    on_info_color: str
    radius: str
    border_width: str
    outline_width: str
    outline_offset: str
    shadow_base: str
    focus_ring_alpha: Decimal
    disabled_opacity: Decimal
    duration_fast: str
    duration_base: str
    duration_slow: str
    ease_standard: str
    ease_out: str
    font_size_base: str
    font_size_staff: str
    font_weight_base: int
    space_unit: str
    density_scale: Decimal


@dataclass(frozen=True)
class ContrastResult:
    """One validated foreground/background pairing."""

    description: str
    foreground: str
    background: str
    ratio: float


@dataclass(frozen=True)
class ResolvedTheme:
    """Complete theme output safe for CSS rendering."""

    colors: dict[str, str]
    css_variables: dict[str, str]
    contrast_results: tuple[ContrastResult, ...]
    contrast_errors: dict[str, list[str]]


def _mix(first: str, second: str, second_weight: float) -> str:
    """Mix two sRGB colors and return a hex value."""
    color = Color(first).mix(second, percent=second_weight, space="srgb")
    return str(color.to_string(hex=True))


def _darken(color: str, amount: float) -> str:
    """Darken a color by mixing with black."""
    return _mix(color, "#000000", amount)


def _on_color(color: str) -> str:
    """Choose the higher-contrast light or dark foreground."""
    black = Color("#111111").contrast(color, method="wcag21")
    white = Color("#ffffff").contrast(color, method="wcag21")
    return "#111111" if black >= white else "#ffffff"


def _accessible_derived(
    foreground: str, background: str, minimum: float = MINIMUM_TEXT_CONTRAST
) -> str:
    """Adjust a derived foreground until it meets contrast."""
    if _contrast(foreground, background) >= minimum:
        return foreground
    for amount in (0.08, 0.16, 0.24, 0.32, 0.45):
        candidate = _darken(foreground, amount)
        if _contrast(candidate, background) >= minimum:
            return candidate
    return _on_color(background)


def _contrast(foreground: str, background: str) -> float:
    """Return WCAG 2.1 contrast."""
    return float(Color(foreground).contrast(background, method="wcag21"))


def _value(source: Any, field: str, fallback: str) -> str:
    """Return an explicit optional value or its resolved fallback."""
    value = str(getattr(source, field) or "")
    return value or fallback


def _rgb(color: str) -> str:
    """Return comma-separated sRGB channels."""
    parsed = Color(color).convert("srgb")
    return ", ".join(str(round(channel * 255)) for channel in parsed.coords())


def resolve_theme(source: ThemeSource) -> ResolvedTheme:
    """Resolve persisted Tier 1/Tier 2 values into a complete theme."""
    primary = source.primary_color
    background = source.background_color
    text = source.text_color
    surface = _value(source, "surface_color", "#ffffff")
    elevated = _value(source, "surface_elevated_color", "#ffffff")
    emphasis = _value(
        source,
        "emphasis_text_color",
        _accessible_derived("#111827", background),
    )
    muted = _value(
        source,
        "muted_text_color",
        _accessible_derived("#667085", background),
    )
    tertiary = _value(
        source,
        "tertiary_text_color",
        _accessible_derived("#7a8291", background),
    )
    disabled = _value(source, "disabled_text_color", muted)
    border = _value(source, "border_color", _mix(background, text, 0.12))

    semantic_defaults = {
        "secondary": source.secondary_color or "#374151",
        "success": source.success_color or "#2f6b3c",
        "warning": source.warning_color or "#8a6100",
        "danger": source.danger_color or "#a93226",
        "info": source.info_color or "#335c9a",
    }
    semantic_surface_defaults = {
        "secondary": "#f0f2f4",
        "success": "#eaf3ec",
        "warning": "#fff8e0",
        "danger": "#fbf0ee",
        "info": "#eef3fa",
    }
    semantic_surfaces = {
        "secondary": _value(
            source,
            "secondary_surface_color",
            semantic_surface_defaults["secondary"],
        ),
        "success": _value(
            source,
            "success_surface_color",
            semantic_surface_defaults["success"],
        ),
        "warning": _value(
            source,
            "warning_surface_color",
            semantic_surface_defaults["warning"],
        ),
        "danger": _value(
            source,
            "danger_surface_color",
            semantic_surface_defaults["danger"],
        ),
        "info": _value(
            source,
            "info_surface_color",
            semantic_surface_defaults["info"],
        ),
    }
    semantic_text = {
        role: _value(source, f"{role}_text_color", semantic_defaults[role])
        for role in semantic_defaults
    }

    colors = {
        "primary": primary,
        "background": background,
        "text": text,
        "surface": surface,
        "surface_elevated": elevated,
        "emphasis_text": emphasis,
        "muted_text": muted,
        "tertiary_text": tertiary,
        "disabled_text": disabled,
        "border": border,
        "link": _value(source, "link_color", primary),
        "link_hover": _value(source, "link_hover_color", _darken(primary, 0.16)),
        "on_primary": _value(source, "on_primary_color", _on_color(primary)),
        "primary_hover": _value(source, "primary_hover_color", _darken(primary, 0.10)),
        "primary_active": _value(
            source, "primary_active_color", _darken(primary, 0.22)
        ),
        "primary_text": _value(source, "primary_text_color", primary),
        "primary_surface": _value(
            source,
            "primary_surface_color",
            _mix(background, primary, 0.12),
        ),
    }
    for role, solid in semantic_defaults.items():
        colors[f"{role}"] = solid
        colors[f"{role}_hover"] = _darken(solid, 0.10)
        colors[f"{role}_active"] = _darken(solid, 0.20)
        colors[f"{role}_text"] = semantic_text[role]
        colors[f"{role}_surface"] = semantic_surfaces[role]
        colors[f"on_{role}"] = _value(
            source,
            f"on_{role}_color",
            _on_color(solid),
        )

    css_variables = {
        **{f"--theme-{key.replace('_', '-')}": value for key, value in colors.items()},
        "--theme-radius": source.radius,
        "--theme-border-width": source.border_width,
        "--theme-outline-width": source.outline_width,
        "--theme-outline-offset": source.outline_offset,
        "--theme-shadow": source.shadow_base,
        "--theme-focus-ring-alpha": str(source.focus_ring_alpha),
        "--theme-disabled-opacity": str(source.disabled_opacity),
        "--theme-duration-fast": source.duration_fast,
        "--theme-duration-base": source.duration_base,
        "--theme-duration-slow": source.duration_slow,
        "--theme-ease-standard": source.ease_standard,
        "--theme-ease-out": source.ease_out,
        "--theme-font-sans": "IBM Plex Sans, system-ui, sans-serif",
        "--theme-font-mono": "IBM Plex Mono, ui-monospace, monospace",
        "--theme-font-size-base": source.font_size_base,
        "--theme-font-size-staff": source.font_size_staff,
        "--theme-font-weight-base": str(source.font_weight_base),
        "--theme-space-unit": source.space_unit,
        "--theme-density-scale": str(source.density_scale),
    }
    for name, value in colors.items():
        css_variables[f"--theme-{name.replace('_', '-')}-rgb"] = _rgb(value)

    checks: list[tuple[str, str, str, str]] = [
        ("Body text on page background", "text_color", text, background),
        ("Body text on surface", "surface_color", text, surface),
        ("Emphasis text on page", "emphasis_text_color", emphasis, background),
        ("Muted text on page", "muted_text_color", muted, background),
        (
            "Links",
            "link_color" if source.link_color else "primary_color",
            colors["link"],
            background,
        ),
        (
            "Hovered links",
            "link_hover_color" if source.link_hover_color else "primary_color",
            colors["link_hover"],
            background,
        ),
        (
            "Text on primary actions",
            "on_primary_color",
            colors["on_primary"],
            primary,
        ),
        (
            "Text on hovered primary actions",
            "on_primary_color",
            colors["on_primary"],
            colors["primary_hover"],
        ),
        (
            "Text on active primary actions",
            "on_primary_color",
            colors["on_primary"],
            colors["primary_active"],
        ),
    ]
    for role in semantic_defaults:
        role_checks = (
            (
                f"{role.title()} text on subtle surface",
                (
                    f"{role}_text_color"
                    if getattr(source, f"{role}_text_color")
                    else f"{role}_surface_color"
                    if getattr(source, f"{role}_surface_color")
                    else f"{role}_color"
                ),
                colors[f"{role}_text"],
                colors[f"{role}_surface"],
            ),
            (
                f"Text on solid {role}",
                (
                    f"on_{role}_color"
                    if getattr(source, f"on_{role}_color")
                    else f"{role}_color"
                ),
                colors[f"on_{role}"],
                colors[role],
            ),
        )
        checks.extend(role_checks)

    contrast_results: list[ContrastResult] = []
    errors: dict[str, list[str]] = {}
    for description, field, foreground, contrast_background in checks:
        ratio = _contrast(foreground, contrast_background)
        result = ContrastResult(description, foreground, contrast_background, ratio)
        contrast_results.append(result)
        if ratio < MINIMUM_TEXT_CONTRAST:
            errors.setdefault(field, []).append(
                f"{description} contrast is {ratio:.2f}:1; "
                f"WCAG AA requires at least {MINIMUM_TEXT_CONTRAST:.1f}:1."
            )

    return ResolvedTheme(
        colors=colors,
        css_variables=css_variables,
        contrast_results=tuple(contrast_results),
        contrast_errors=errors,
    )


def get_resolved_theme(source: ThemeSource, revision: int = 0) -> ResolvedTheme:
    """Return a cached resolved theme for the persisted revision."""
    cache_key = f"site_settings:resolved_theme:{revision}"
    resolved: ResolvedTheme | None = cache.get(cache_key)
    if resolved is None:
        resolved = resolve_theme(source)
        cache.set(cache_key, resolved, timeout=None)
    return resolved
