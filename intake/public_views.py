"""Public pages: follow your own reports, and search open issues."""

import math
from typing import Any

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.shortcuts import redirect
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.generic import TemplateView
from global_login_required import login_not_required

from intake.services.map_config import public_map_config
from intake.services.public_search import (
    SearchCriteria,
    parse_query,
    search_open_issues,
)
from intake.services.rate_limit import (
    ISSUE_TEXT_SEARCH,
    RATE_LIMITED,
    REFERENCE_LOOKUP,
    client_address,
    reserve,
)
from intake.services.tracking import (
    forget_reference,
    remember_reference,
    tracked_reports,
)
from site_settings.configuration import get_site_configuration

MAX_RADIUS_KM = 50.0
MAX_QUERY_LENGTH = 300


class FeatureEnabledMixin(View):
    """Hide a public page unless the organisation has switched it on."""

    feature_field = ""

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Check the database-backed switch before serving the page."""
        if not getattr(get_site_configuration(), self.feature_field):
            raise Http404
        return super().dispatch(request, *args, **kwargs)


@method_decorator(login_not_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class TrackReportsView(FeatureEnabledMixin, TemplateView):
    """Show the status of reports this browser submitted or was told to follow."""

    template_name = "intake/track_reports.html"
    feature_field = "public_tracking_enabled"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """List followed reports with their current public status."""
        context = super().get_context_data(**kwargs)
        context["reports"] = tracked_reports(self.request.session)
        return context

    def post(self, request: HttpRequest) -> HttpResponse:
        """Follow a report by its reference, or stop following one."""
        reference = request.POST.get("reference", "")[:40]
        if request.POST.get("action") == "remove":
            forget_reference(request.session, reference)
            messages.success(request, "That report is no longer listed here.")
            return redirect("intake:track_reports")
        try:
            reserve(REFERENCE_LOOKUP, client_address(request))
        except ValidationError as error:
            messages.error(request, " ".join(error.messages))
            return redirect("intake:track_reports")
        if remember_reference(request.session, reference):
            messages.success(request, "Report added to your list.")
        else:
            messages.error(
                request,
                "We could not add that reference. Check it, or you may already "
                "be following the most reports allowed.",
            )
        return redirect("intake:track_reports")


@method_decorator(login_not_required, name="dispatch")
class IssueSearchView(FeatureEnabledMixin, TemplateView):
    """Page for finding open issues by plain-language search or on a map."""

    template_name = "intake/search_issues.html"
    feature_field = "public_search_enabled"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Provide the optional map settings."""
        context = super().get_context_data(**kwargs)
        map_config = public_map_config()
        context["map_config"] = map_config
        context["map_attribution"] = map_config["attribution"] if map_config else ""
        return context


def _number(params: Any, name: str, low: float, high: float) -> float | None:
    raw = params.get(name)
    if raw in (None, ""):
        return None
    value = float(raw)
    if not math.isfinite(value) or not low <= value <= high:
        raise ValueError(name)
    return value


@method_decorator(login_not_required, name="dispatch")
class IssueSearchApiView(FeatureEnabledMixin, View):
    """Return open issues for a text query, a point and radius, or a map area."""

    http_method_names = ["get"]
    feature_field = "public_search_enabled"

    def get(self, request: HttpRequest) -> JsonResponse:
        """Search open issues; every parameter is optional."""
        params = request.GET
        text = params.get("q", "").strip()
        if len(text) > MAX_QUERY_LENGTH:
            return JsonResponse({"error": "That search is too long."}, status=400)
        try:
            lat = _number(params, "lat", -90, 90)
            lng = _number(params, "lng", -180, 180)
            radius = _number(params, "radius_km", 0.001, MAX_RADIUS_KM)
            south = _number(params, "south", -90, 90)
            north = _number(params, "north", -90, 90)
            west = _number(params, "west", -180, 180)
            east = _number(params, "east", -180, 180)
        except ValueError:
            return JsonResponse({"error": "A search value was not valid."}, status=400)
        if text:
            try:
                reserve(ISSUE_TEXT_SEARCH, client_address(request))
            except ValidationError as error:
                status = 429 if error.code == RATE_LIMITED else 400
                return JsonResponse({"error": " ".join(error.messages)}, status=status)
            criteria = parse_query(text)
        else:
            criteria = SearchCriteria()
        if (lat is None) != (lng is None):
            return JsonResponse({"error": "Give both lat and lng."}, status=400)
        if lat is not None and lng is not None and criteria.center is None:
            criteria.center = (lat, lng)
            criteria.understood.append("near the chosen point")
        if criteria.center is not None and criteria.radius_km is None:
            criteria.radius_km = radius or float(
                get_site_configuration().public_search_radius_km
            )
        edges = (south, west, north, east)
        if any(edge is not None for edge in edges):
            if None in edges or south > north or west > east:  # type: ignore[operator]
                return JsonResponse(
                    {"error": "The map area was not valid."}, status=400
                )
            criteria.bounds = edges  # type: ignore[assignment]
        return JsonResponse(search_open_issues(criteria).as_json())
