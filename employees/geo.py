"""Street addresses and rough travel estimates for officers' jobs.

Travel is estimated from straight-line distance, not real roads: good
enough to plan a day, and swappable for a routing service later.
"""

import json
import logging
import math
import threading
import time
import urllib.parse
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.cache import cache
from django.utils import timezone

from site_settings.configuration import get_site_configuration

from .work_models import WorkItem

logger = logging.getLogger(__name__)

SPEED_KMH = 30  # typical urban driving speed
ROAD_FACTOR = 1.3  # roads are longer than a straight line
ON_SITE_MINUTES = 45  # assumed time on site per job

NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
_lookup_lock = threading.Lock()
_last_lookup = 0.0


def distance_km(a_lat: float, a_lng: float, b_lat: float, b_lng: float) -> float:
    """Return the great-circle distance between two points in km."""
    r = math.pi / 180
    d_lat = (b_lat - a_lat) * r
    d_lng = (b_lng - a_lng) * r
    x = (
        math.sin(d_lat / 2) ** 2
        + math.cos(a_lat * r) * math.cos(b_lat * r) * math.sin(d_lng / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(x))


def _coords(item: WorkItem) -> tuple[float, float]:
    return float(item.latitude), float(item.longitude)


def depot() -> tuple[float, float]:
    """Return where officers start and end their day."""
    configuration = get_site_configuration()
    return (
        float(configuration.depot_latitude),
        float(configuration.depot_longitude),
    )


@dataclass
class Leg:
    """Travel to one job and the estimated arrival there."""

    eta: datetime
    travel_minutes: float
    km: float


@dataclass
class DayPlan:
    """Estimated travel for the officer's remaining jobs, in order."""

    legs: dict[int, Leg] = field(default_factory=dict)
    finish: datetime | None = None
    travel_minutes: float = 0
    km: float = 0


def _travel(km: float) -> tuple[float, float]:
    configuration = get_site_configuration()
    road_km = km * float(configuration.road_factor)
    return road_km, road_km / float(configuration.travel_speed_kmh) * 60


def plan_day(jobs: Sequence[WorkItem], *, on_site: WorkItem | None = None) -> DayPlan:
    """Estimate arrival times from the depot through each job and back.

    If the officer is already on site at a job, the day continues from
    there once that job is finished.
    """
    now = timezone.now()
    plan = DayPlan()
    position = depot()
    clock = now
    if on_site is not None:
        position = _coords(on_site)
        plan.legs[on_site.pk] = Leg(eta=now, travel_minutes=0, km=0)
        clock = now + timedelta(minutes=get_site_configuration().on_site_minutes)
    for job in jobs:
        if job is on_site:
            continue
        km, minutes = _travel(distance_km(*position, *_coords(job)))
        eta = clock + timedelta(minutes=minutes)
        plan.legs[job.pk] = Leg(eta=eta, travel_minutes=minutes, km=km)
        plan.travel_minutes += minutes
        plan.km += km
        clock = eta + timedelta(minutes=get_site_configuration().on_site_minutes)
        position = _coords(job)
    if plan.legs:
        km, minutes = _travel(distance_km(*position, *depot()))
        plan.travel_minutes += minutes
        plan.km += km
        plan.finish = clock + timedelta(minutes=minutes)
    return plan


def _cache_key(lat: Decimal | float, lng: Decimal | float) -> str:
    return f"street-address:{float(lat):.5f},{float(lng):.5f}"


def _lookup(lat: float, lng: float) -> str:
    """Ask OpenStreetMap's Nominatim for the address at a point.

    Nominatim allows one request a second and asks apps to identify
    themselves, so lookups are spaced out and every answer is cached.
    """
    global _last_lookup
    query = urllib.parse.urlencode(
        {"lat": lat, "lon": lng, "format": "jsonv2", "zoom": 18}
    )
    request = urllib.request.Request(  # noqa: S310
        f"{NOMINATIM_URL}?{query}",
        headers={"User-Agent": settings.GEOCODER_USER_AGENT},
    )
    with _lookup_lock:
        wait = 1 - (time.monotonic() - _last_lookup)
        if wait > 0:
            time.sleep(wait)
        _last_lookup = time.monotonic()
        with urllib.request.urlopen(request, timeout=4) as response:  # noqa: S310
            data = json.load(response)
    parts = data.get("address", {})
    street = " ".join(
        part for part in (parts.get("house_number"), parts.get("road")) if part
    )
    area = parts.get("suburb") or parts.get("neighbourhood") or parts.get("city")
    postcode = parts.get("postcode")
    return ", ".join(part for part in (street, area, postcode) if part)


def street_address(item: WorkItem) -> str:
    """Return the street address for a job's location, or its coordinates."""
    fallback = f"{item.latitude}, {item.longitude}"
    if not settings.REVERSE_GEOCODING:
        return fallback
    key = _cache_key(item.latitude, item.longitude)
    address = cache.get(key)
    if address is None:
        try:
            address = _lookup(*_coords(item))
        except OSError, ValueError:
            logger.warning("Address lookup failed for work item %s", item.pk)
            return fallback
        cache.set(key, address, timeout=None)
    return address or fallback
