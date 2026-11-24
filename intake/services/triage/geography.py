"""Validate geographic coverage and evaluate a reported map pin."""

import math
from enum import StrEnum
from typing import Any

from django.core.exceptions import ValidationError
from shapely.errors import GEOSException
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry


class Coverage(StrEnum):
    """Geographic evidence, not an ownership or scope decision."""

    INSIDE = "inside"
    OUTSIDE = "outside"
    BOUNDARY = "boundary"
    UNKNOWN = "unknown"


def parse_service_area(value: Any) -> BaseGeometry:
    """Parse a valid, non-antimeridian WGS84 GeoJSON polygon or feature."""
    if not isinstance(value, dict):
        raise ValidationError("The service area must be a GeoJSON object.")
    geometry: Any = value
    if value.get("type") == "Feature":
        geometry = value.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type") not in (
        "Polygon",
        "MultiPolygon",
    ):
        raise ValidationError("The service area must be a Polygon or MultiPolygon.")
    coordinates = geometry.get("coordinates")
    polygons = [coordinates] if geometry["type"] == "Polygon" else coordinates
    if not isinstance(polygons, list) or not polygons:
        raise ValidationError("The service area must contain at least one polygon.")
    for polygon in polygons:
        if not isinstance(polygon, list) or not polygon:
            raise ValidationError("Each polygon must contain at least one ring.")
        for ring in polygon:
            if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                raise ValidationError("Each polygon ring must be closed.")
            previous_longitude: float | int | None = None
            for position in ring:
                if (
                    not isinstance(position, list)
                    or len(position) != 2
                    or any(
                        isinstance(n, bool)
                        or not isinstance(n, (int, float))
                        or (isinstance(n, float) and not math.isfinite(n))
                        for n in position
                    )
                ):
                    raise ValidationError(
                        "Each position must have finite longitude and latitude."
                    )
                lon, lat = position
                if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                    raise ValidationError(
                        "Service-area coordinates must be valid WGS84 values."
                    )
                if (
                    previous_longitude is not None
                    and abs(lon - previous_longitude) > 180
                ):
                    raise ValidationError(
                        "Service areas crossing the antimeridian are not supported."
                    )
                previous_longitude = lon
    try:
        area = shape(geometry)
    except (ValueError, TypeError, GEOSException) as exc:
        raise ValidationError("The service-area geometry is invalid.") from exc
    if area.is_empty or not area.is_valid:
        raise ValidationError("The service-area geometry is empty or invalid.")
    return area


def evaluate_coverage(
    area: BaseGeometry | None, latitude: float | None, longitude: float | None
) -> Coverage:
    """Assess coverage without inferring responsibility for the reported asset."""
    if area is None or latitude is None or longitude is None:
        return Coverage.UNKNOWN
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return Coverage.UNKNOWN
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        return Coverage.UNKNOWN
    point = Point(longitude, latitude)
    if area.touches(point):
        return Coverage.BOUNDARY
    return Coverage.INSIDE if area.contains(point) else Coverage.OUTSIDE
