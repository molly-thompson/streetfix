"""Tests for deployment-configured public map settings."""

from pytest_django.fixtures import Settings

from intake.services.map_config import intake_map_config

MAP_CONFIG = {
    "tile_url": "https://tiles.example.test/{z}/{x}/{y}.png",
    "attribution": "Example tiles",
    "latitude": "51.5",
    "longitude": "-0.12",
    "zoom": "13",
}


def test_no_provider_is_selected_by_default(settings: Settings) -> None:
    """Unconfigured deployments do not contact an external tile service."""
    settings.INTAKE_MAP = {}
    assert intake_map_config() is None


def test_valid_deployment_map_configuration(settings: Settings) -> None:
    """Explicit tile provider, attribution and centre are retained."""
    settings.INTAKE_MAP = MAP_CONFIG
    result = intake_map_config()
    assert result is not None
    assert result.tile_url == MAP_CONFIG["tile_url"]
    assert result.latitude == 51.5
    assert result.longitude == -0.12


def test_invalid_map_configuration_is_disabled(settings: Settings) -> None:
    """Unsafe, incomplete, or unusable map settings do not reach the browser."""
    for changed in (
        {"tile_url": "http://tiles.example.test/{z}/{x}/{y}"},
        {"tile_url": "https://u:password@tiles.example.test/{z}/{x}/{y}"},
        {"tile_url": "https://tiles.example.test/{z}/{x}/{unknown}"},
        {"tile_url": "https://tiles.example.test/{z}/{x}/{y}/{broken"},
        {"latitude": "nan"},
        {"longitude": "181"},
        {"zoom": "100"},
        {"attribution": "  "},
    ):
        settings.INTAKE_MAP = {**MAP_CONFIG, **changed}
        assert intake_map_config() is None
