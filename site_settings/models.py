"""Models for site-wide configuration."""

from typing import Any

from cloudinary.models import CloudinaryField
from colorfield.fields import ColorField
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models

SITE_NAME_VALIDATOR = RegexValidator(
    regex=r"\S",
    message="Enter a site name containing at least one non-whitespace character.",
)

RADIUS_VALIDATOR = RegexValidator(
    regex=r"^(?:0|(?:\d+(?:\.\d+)?)(?:px|rem|em))$",
    message="Enter a radius using px, rem, or em units, or 0.",
)

MINIMUM_TEXT_CONTRAST = 4.5
DEFAULT_SUCCESS_COLOR = "#166534"
DEFAULT_WARNING_COLOR = "#92400e"
DEFAULT_DANGER_COLOR = "#b91c1c"

CSS_LENGTH_VALIDATOR = RegexValidator(
    regex=r"^(?:0|(?:\d+(?:\.\d+)?)(?:px|rem|em|%))$",
    message="Enter a CSS length using px, rem, em, or %, or 0.",
)

CSS_TIME_VALIDATOR = RegexValidator(
    regex=r"^\d+(?:\.\d+)?(?:ms|s)$",
    message="Enter a duration using ms or s.",
)

CSS_SAFE_VALUE_VALIDATOR = RegexValidator(
    regex=r"^(?!.*[;{}<>])[\s\S]+$",
    message="Enter a CSS value without declaration separators or markup.",
)


class SiteConfiguration(models.Model):
    """Singleton organisation configuration shared across applications."""

    locale_code = models.CharField(max_length=35, default="en-GB")
    language_code = models.CharField(max_length=10, default="en")
    time_zone = models.CharField(max_length=50, default="Europe/London")
    country_code = models.CharField(max_length=2, default="GB")
    reference_prefix = models.CharField(max_length=20, default="SF-")
    duplicate_radius_km = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default="0.200",
    )
    duplicate_window_days = models.PositiveIntegerField(default=30)
    waiting_too_long_days = models.PositiveIntegerField(default=7)
    depot_name = models.CharField(
        max_length=150,
        default="Council House, Victoria Square",
    )
    depot_latitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        default="52.479700",
    )
    depot_longitude = models.DecimalField(
        max_digits=9,
        decimal_places=6,
        default="-1.902600",
    )
    travel_speed_kmh = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default="30.00",
    )
    road_factor = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        default="1.30",
    )
    on_site_minutes = models.PositiveIntegerField(default=45)
    max_photo_bytes = models.PositiveIntegerField(default=5 * 1024 * 1024)
    no_photo_reason_min_length = models.PositiveIntegerField(default=15)
    postcode_cache_seconds = models.PositiveIntegerField(default=60 * 60 * 24)

    class Meta:
        verbose_name = "site configuration"
        verbose_name_plural = "site configuration"

    def __str__(self) -> str:
        """Return the settings label shown in the admin."""
        return "Site configuration"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Persist the singleton configuration row."""
        self.pk = 1
        super().save(*args, **kwargs)
        cache.delete("site_settings:site_configuration")


class ThemeSettings(models.Model):
    """The singleton theme configuration for the site."""

    site_name = models.CharField(
        max_length=100,
        default="Project",
        validators=[SITE_NAME_VALIDATOR],
    )
    favicon = CloudinaryField(
        "favicon",
        resource_type="image",
        blank=True,
        null=True,
    )
    brand_image = CloudinaryField(
        "brand image",
        resource_type="image",
        blank=True,
        null=True,
    )
    primary_color = ColorField(
        "primary color",
        max_length=7,
        default="#0f6b63",
    )
    background_color = ColorField(
        "page background",
        max_length=7,
        default="#f5f6f8",
    )
    text_color = ColorField(
        "text color",
        max_length=7,
        default="#374151",
    )
    radius = models.CharField(
        max_length=12,
        default="0.375rem",
        validators=[RADIUS_VALIDATOR],
    )

    surface_color = ColorField(
        "surface color",
        max_length=7,
        blank=True,
        default="",
    )
    emphasis_text_color = ColorField(
        "emphasis text color",
        max_length=7,
        blank=True,
        default="",
    )
    border_color = ColorField(
        "border color",
        max_length=7,
        blank=True,
        default="",
    )
    muted_text_color = ColorField(
        "muted text color",
        max_length=7,
        blank=True,
        default="",
    )
    link_color = ColorField(
        "link color",
        max_length=7,
        blank=True,
        default="",
    )
    link_hover_color = ColorField(
        "link hover color",
        max_length=7,
        blank=True,
        default="",
    )
    on_primary_color = ColorField(
        "text on primary color",
        max_length=7,
        blank=True,
        default="",
    )
    primary_hover_color = ColorField(
        "primary hover color",
        max_length=7,
        blank=True,
        default="",
    )
    primary_active_color = ColorField(
        "primary active color",
        max_length=7,
        blank=True,
        default="",
    )
    secondary_color = ColorField(
        "secondary color",
        max_length=7,
        blank=True,
        default="",
    )
    success_color = ColorField(
        "success color",
        max_length=7,
        blank=True,
        default="",
    )
    warning_color = ColorField(
        "warning color",
        max_length=7,
        blank=True,
        default="",
    )
    danger_color = ColorField(
        "danger color",
        max_length=7,
        blank=True,
        default="",
    )
    success_surface_color = ColorField(
        "success alert background",
        max_length=7,
        blank=True,
        default="",
    )
    warning_surface_color = ColorField(
        "warning alert background",
        max_length=7,
        blank=True,
        default="",
    )
    danger_surface_color = ColorField(
        "danger alert background",
        max_length=7,
        blank=True,
        default="",
    )
    surface_elevated_color = ColorField(
        "elevated surface",
        max_length=7,
        blank=True,
        default="",
    )
    tertiary_text_color = ColorField(
        "tertiary text color",
        max_length=7,
        blank=True,
        default="",
    )
    disabled_text_color = ColorField(
        "disabled text color",
        max_length=7,
        blank=True,
        default="",
    )
    primary_text_color = ColorField(
        "primary text color",
        max_length=7,
        blank=True,
        default="",
    )
    primary_surface_color = ColorField(
        "primary surface color",
        max_length=7,
        blank=True,
        default="",
    )
    info_color = ColorField(
        "info color",
        max_length=7,
        blank=True,
        default="",
    )
    secondary_text_color = ColorField(
        "secondary text color",
        max_length=7,
        blank=True,
        default="",
    )
    secondary_surface_color = ColorField(
        "secondary surface color",
        max_length=7,
        blank=True,
        default="",
    )
    success_text_color = ColorField(
        "success text color",
        max_length=7,
        blank=True,
        default="",
    )
    warning_text_color = ColorField(
        "warning text color",
        max_length=7,
        blank=True,
        default="",
    )
    danger_text_color = ColorField(
        "danger text color",
        max_length=7,
        blank=True,
        default="",
    )
    info_text_color = ColorField(
        "info text color",
        max_length=7,
        blank=True,
        default="",
    )
    info_surface_color = ColorField(
        "info surface color",
        max_length=7,
        blank=True,
        default="",
    )
    on_secondary_color = ColorField(
        "text on secondary color",
        max_length=7,
        blank=True,
        default="",
    )
    on_success_color = ColorField(
        "text on success color",
        max_length=7,
        blank=True,
        default="",
    )
    on_warning_color = ColorField(
        "text on warning color",
        max_length=7,
        blank=True,
        default="",
    )
    on_danger_color = ColorField(
        "text on danger color",
        max_length=7,
        blank=True,
        default="",
    )
    on_info_color = ColorField(
        "text on info color",
        max_length=7,
        blank=True,
        default="",
    )
    border_width = models.CharField(
        max_length=12,
        default="1px",
        validators=[CSS_LENGTH_VALIDATOR],
    )
    outline_width = models.CharField(
        max_length=12,
        default="3px",
        validators=[CSS_LENGTH_VALIDATOR],
    )
    outline_offset = models.CharField(
        max_length=12,
        default="2px",
        validators=[CSS_LENGTH_VALIDATOR],
    )
    shadow_base = models.CharField(
        max_length=120,
        default="0 1px 2px rgba(15, 23, 42, 0.12)",
        validators=[CSS_SAFE_VALUE_VALIDATOR],
    )
    focus_ring_alpha = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default="0.35",
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    disabled_opacity = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default="0.60",
        validators=[MinValueValidator(0), MaxValueValidator(1)],
    )
    duration_fast = models.CharField(
        max_length=12,
        default="120ms",
        validators=[CSS_TIME_VALIDATOR],
    )
    duration_base = models.CharField(
        max_length=12,
        default="180ms",
        validators=[CSS_TIME_VALIDATOR],
    )
    duration_slow = models.CharField(
        max_length=12,
        default="300ms",
        validators=[CSS_TIME_VALIDATOR],
    )
    ease_standard = models.CharField(
        max_length=80,
        default="cubic-bezier(0.2, 0, 0, 1)",
        validators=[CSS_SAFE_VALUE_VALIDATOR],
    )
    ease_out = models.CharField(
        max_length=80,
        default="cubic-bezier(0, 0, 0.2, 1)",
        validators=[CSS_SAFE_VALUE_VALIDATOR],
    )
    font_size_base = models.CharField(
        max_length=12,
        default="1rem",
        validators=[CSS_LENGTH_VALIDATOR],
    )
    font_size_staff = models.CharField(
        max_length=12,
        default="0.875rem",
        validators=[CSS_LENGTH_VALIDATOR],
    )
    font_weight_base = models.PositiveSmallIntegerField(default=400)
    space_unit = models.CharField(
        max_length=12,
        default="0.25rem",
        validators=[CSS_LENGTH_VALIDATOR],
    )
    density_scale = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default="1.00",
    )
    revision = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        verbose_name = "theme settings"
        verbose_name_plural = "theme settings"

    def __str__(self) -> str:
        """Return the settings label shown in the admin."""
        return "Site theme"

    def save(self, *args: Any, **kwargs: Any) -> None:
        """Validate values and persist the singleton settings row."""
        self.pk = 1
        existed = ThemeSettings.objects.filter(pk=1).exists()
        self.clean_fields()
        self.clean()
        if existed:
            self.revision = (
                ThemeSettings.objects.only("revision").get(pk=1).revision + 1
            )
        super().save(*args, **kwargs)
        if not existed:
            cache.delete("site_settings:resolved_theme:0")
        cache.delete(f"site_settings:resolved_theme:{self.revision - 1}")
        cache.delete(f"site_settings:resolved_theme:{self.revision}")

    def clean(self) -> None:
        """Validate WCAG AA contrast for the foreground/background pairs."""
        super().clean()
        from .theme import resolve_theme

        errors = resolve_theme(self).contrast_errors
        if errors:
            raise ValidationError(errors)
