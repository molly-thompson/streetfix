"""Public report form and the browser's signed photo-upload endpoints."""

import json
import logging
from typing import Any
from uuid import UUID

import cloudinary.exceptions
from django.conf import settings
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.http.response import HttpResponseBase
from django.urls import reverse_lazy
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.generic import FormView, TemplateView
from global_login_required import login_not_required

from employees.organisation_models import IssueType
from intake.forms import ReportSubmissionForm
from intake.models import ContactMethod
from intake.services.map_config import public_map_config
from intake.services.photo_reservations import verify_photo_slot
from intake.services.photo_upload import authorize_upload, photo_upload_enabled
from intake.services.rate_limit import (
    RATE_LIMITED,
    REPORT_SUBMISSION,
    client_address,
    reserve,
)

logger = logging.getLogger(__name__)


class PublicReportingEnabledMixin(View):
    """Prevent access until a deployment explicitly enables public reporting."""

    def dispatch(
        self, request: HttpRequest, *args: Any, **kwargs: Any
    ) -> HttpResponseBase:
        """Check the deployment gate before displaying or accepting a report."""
        if not settings.INTAKE_PUBLIC_REPORTING_ENABLED:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def session_key(request: HttpRequest) -> str:
    """Return the browser session's key, starting a session if needed."""
    if not request.session.session_key:
        request.session.create()
    return str(request.session.session_key)


@method_decorator(login_not_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class SubmitReportView(PublicReportingEnabledMixin, FormView):  # type: ignore[type-arg]
    """Collect and save a public report before triage."""

    form_class = ReportSubmissionForm
    template_name = "intake/submit_report.html"
    success_url = reverse_lazy("intake:report_received")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Provide taxonomy, map and photo settings for progressive enhancement."""
        context = super().get_context_data(**kwargs)
        context["issue_tree"] = list(
            IssueType.objects.filter(active=True)
            .order_by("sort_order", "name")
            .values("id", "parent_id", "name", "kind")
        )
        map_config = public_map_config()
        if map_config is not None:
            context["map_config"] = map_config
            context["map_attribution"] = map_config["attribution"]
        context["contact_methods"] = {
            str(method.pk): method.code for method in ContactMethod.objects.all()
        }
        context["photos_enabled"] = photo_upload_enabled()
        return context

    def form_valid(self, form: ReportSubmissionForm) -> HttpResponse:
        """Limit submissions per address, then persist the report."""
        try:
            reserve(REPORT_SUBMISSION, client_address(self.request))
            form.save(session_key=session_key(self.request))
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        return super().form_valid(form)


@method_decorator(login_not_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class ReportReceivedView(PublicReportingEnabledMixin, TemplateView):
    """Confirm receipt without exposing a report identifier."""

    template_name = "intake/report_received.html"


def _error(exc: ValidationError) -> JsonResponse:
    status = 429 if exc.code == RATE_LIMITED else 400
    return JsonResponse({"error": " ".join(exc.messages)}, status=status)


@method_decorator(login_not_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class PhotoAuthorizeView(PublicReportingEnabledMixin, View):
    """Reserve a photo slot and return a signed direct-upload request."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> JsonResponse:
        """Authorize one upload for the browser's open photo draft."""
        try:
            raw = json.loads(request.body or b"{}")
            draft = raw.get("draft") if isinstance(raw, dict) else None
            draft_id = UUID(draft) if draft else None
        except ValueError, TypeError:
            return JsonResponse({"error": "The request could not be read."}, status=400)
        try:
            grant = authorize_upload(
                session_key=session_key(request),
                address=client_address(request),
                draft_id=draft_id,
            )
        except ValidationError as exc:
            return _error(exc)
        return JsonResponse(
            {
                "draft": str(grant.draft_id),
                "slot": str(grant.slot_id),
                "upload_url": grant.upload_url,
                "fields": grant.fields,
            },
            status=201,
        )


@method_decorator(login_not_required, name="dispatch")
@method_decorator(never_cache, name="dispatch")
class PhotoVerifyView(PublicReportingEnabledMixin, View):
    """Confirm with the provider that a reserved photo finished uploading."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest, draft_id: UUID, slot_id: UUID) -> JsonResponse:
        """Record verified metadata for the browser's own reserved slot."""
        try:
            slot = verify_photo_slot(
                draft_id=draft_id, slot_id=slot_id, session_key=session_key(request)
            )
        except ValidationError as exc:
            return _error(exc)
        except cloudinary.exceptions.NotFound:
            return JsonResponse(
                {"error": "The photo has not finished uploading."}, status=404
            )
        except cloudinary.exceptions.Error:
            logger.exception("Could not verify report photo %s", slot_id)
            return JsonResponse(
                {"error": "The photo could not be checked."}, status=502
            )
        return JsonResponse({"slot": str(slot.pk), "format": slot.format})
