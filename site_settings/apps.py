"""Application configuration for site-wide settings."""

from django.apps import AppConfig


class SiteSettingsConfig(AppConfig):
    """Configuration for the site settings application."""

    name = "site_settings"

    def ready(self) -> None:
        """Connect configuration cache invalidation."""
        from django.db.models.signals import post_delete, post_save

        from .models import SiteConfiguration

        def invalidate_cache(**kwargs: object) -> None:
            from .configuration import clear_site_configuration_cache

            clear_site_configuration_cache()

        post_save.connect(invalidate_cache, sender=SiteConfiguration)
        post_delete.connect(invalidate_cache, sender=SiteConfiguration)
