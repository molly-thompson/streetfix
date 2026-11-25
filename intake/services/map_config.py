"""Validate optional deployment-specific public map configuration."""

import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib.staticfiles.storage import staticfiles_storage


@dataclass(frozen=True)
class IntakeMapConfig:
    """Public tile settings safe to send to a browser."""

    tile_url: str
    attribution: str
    latitude: float
    longitude: float
    zoom: int


def public_map_config() -> dict[str, Any] | None:
    """Return the browser-safe map settings, with exact marker icon URLs."""
    config = intake_map_config()
    if config is None:
        return None
    return {
        "tile_url": config.tile_url,
        "attribution": config.attribution,
        "latitude": config.latitude,
        "longitude": config.longitude,
        "zoom": config.zoom,
        "icons": {
            name: staticfiles_storage.url(f"vendor/leaflet/images/{name}.png")
            for name in ("marker-icon", "marker-icon-2x", "marker-shadow")
        },
    }


def intake_map_config() -> IntakeMapConfig | None:
    """Disable the map unless all deployment-specific settings are valid."""
    config = settings.INTAKE_MAP
    try:
        tile_url = config["tile_url"].strip()
        attribution = config["attribution"].strip()
        latitude = float(config["latitude"])
        longitude = float(config["longitude"])
        zoom = int(config["zoom"])
        parts = urlsplit(tile_url)
    except AttributeError, KeyError, TypeError, ValueError:
        return None
    tokens = re.findall(r"\{([^{}]+)\}", tile_url)
    remaining = re.sub(r"\{[^{}]+\}", "", tile_url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or not {"z", "x", "y"}.issubset(tokens)
        or set(tokens) - {"z", "x", "y", "s", "r"}
        or "{" in remaining
        or "}" in remaining
        or not attribution
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
        or not 0 <= zoom <= 22
    ):
        return None
    return IntakeMapConfig(tile_url, attribution, latitude, longitude, zoom)
