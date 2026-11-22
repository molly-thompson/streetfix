"""Admin configuration for site-wide settings."""

from django.contrib import admin
from django.http import HttpRequest

from site_settings.models import SiteConfiguration, ThemeSettings


@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Expose organisation-wide configuration."""

    fieldsets = [
        (
            "Locale",
            {
                "fields": (
                    "locale_code",
                    "language_code",
                    "time_zone",
                    "country_code",
                )
            },
        ),
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Allow creating settings only when the singleton does not exist."""
        return not SiteConfiguration.objects.filter(pk=1).exists()

    def has_delete_permission(
        self, request: HttpRequest, obj: SiteConfiguration | None = None
    ) -> bool:
        """Keep the site configuration from being accidentally deleted."""
        return False


@admin.register(ThemeSettings)
class ThemeSettingsAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Expose the singleton theme settings to site administrators."""

    fieldsets = [
        (
            "Branding",
            {"fields": ("site_name", "brand_image", "favicon")},
        ),
        (
            "Typography and geometry",
            {
                "fields": (
                    "font_size_base",
                    "font_size_staff",
                    "font_weight_base",
                    "space_unit",
                    "density_scale",
                    "radius",
                    "border_width",
                    "outline_width",
                    "outline_offset",
                )
            },
        ),
        (
            "Core colors",
            {"fields": ("primary_color", "background_color", "text_color")},
        ),
        (
            "Neutral and primary overrides",
            {
                "fields": (
                    "surface_color",
                    "surface_elevated_color",
                    "emphasis_text_color",
                    "muted_text_color",
                    "tertiary_text_color",
                    "disabled_text_color",
                    "border_color",
                    "link_color",
                    "link_hover_color",
                    "on_primary_color",
                    "primary_hover_color",
                    "primary_active_color",
                    "primary_text_color",
                    "primary_surface_color",
                ),
            },
        ),
        (
            "Semantic overrides",
            {
                "fields": (
                    "secondary_color",
                    "secondary_text_color",
                    "secondary_surface_color",
                    "on_secondary_color",
                    "success_color",
                    "success_text_color",
                    "success_surface_color",
                    "on_success_color",
                    "warning_color",
                    "warning_text_color",
                    "warning_surface_color",
                    "on_warning_color",
                    "danger_color",
                    "danger_surface_color",
                    "danger_text_color",
                    "on_danger_color",
                    "info_color",
                    "info_text_color",
                    "info_surface_color",
                    "on_info_color",
                ),
                "description": (
                    "Leave a value blank to use the theme-derived or default value."
                ),
            },
        ),
        (
            "Motion and elevation",
            {
                "fields": (
                    "shadow_base",
                    "focus_ring_alpha",
                    "disabled_opacity",
                    "duration_fast",
                    "duration_base",
                    "duration_slow",
                    "ease_standard",
                    "ease_out",
                )
            },
        ),
    ]

    def has_add_permission(self, request: HttpRequest) -> bool:
        """Allow creating settings only when the singleton does not exist."""
        return not ThemeSettings.objects.filter(
            pk=1
        ).exists() and super().has_add_permission(request)

    def has_delete_permission(
        self, request: HttpRequest, obj: ThemeSettings | None = None
    ) -> bool:
        """Keep the site configuration from being accidentally deleted."""
        return False
