"""Shared helpers for database-backed application configuration."""

from django.core.cache import cache

from .models import SiteConfiguration

CACHE_KEY = "site_settings:site_configuration"


def get_site_configuration() -> SiteConfiguration:
    """Return the singleton configuration or an unsaved safe default."""
    configuration = cache.get(CACHE_KEY)
    if configuration is None:
        configuration = SiteConfiguration.objects.filter(pk=1).first()
        if configuration is not None:
            cache.set(CACHE_KEY, configuration, timeout=None)
    return configuration or SiteConfiguration()


def clear_site_configuration_cache() -> None:
    """Invalidate cached singleton configuration."""
    cache.delete(CACHE_KEY)
