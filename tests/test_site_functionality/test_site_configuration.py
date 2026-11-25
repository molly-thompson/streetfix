"""Tests for database-backed site configuration."""

import pytest
from django.core.cache import cache

from site_settings.configuration import get_site_configuration
from site_settings.models import SiteConfiguration

pytestmark = pytest.mark.django_db


def test_missing_configuration_has_safe_defaults() -> None:
    """Use safe defaults before the singleton has been created."""
    cache.delete("site_settings:site_configuration")

    configuration = get_site_configuration()

    assert configuration.locale_code == "en-GB"
    assert configuration.language_code == "en"
    assert configuration.time_zone == "Europe/London"
    assert configuration.country_code == "GB"


def test_configuration_is_singleton_and_cached() -> None:
    """Persist one configuration row and invalidate cache after saves."""
    cache.delete("site_settings:site_configuration")
    configuration, _ = SiteConfiguration.objects.update_or_create(
        pk=1,
        defaults={
            "locale_code": "cy-GB",
            "language_code": "cy",
            "time_zone": "Europe/London",
            "country_code": "GB",
        },
    )

    loaded = get_site_configuration()

    assert loaded.pk == 1
    assert loaded.locale_code == "cy-GB"
    assert loaded.time_zone == "Europe/London"

    configuration.language_code = "pl"
    configuration.save(update_fields=("language_code",))

    assert get_site_configuration().language_code == "pl"
