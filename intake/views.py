"""Views for the intake application.

The public report chat is the site's home page; the JSON views behind it
create reports, look up their status and find possible duplicates.
"""

from typing import Any

from django.core.exceptions import ValidationError
from django.http import HttpRequest, JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import RedirectView, TemplateView
from global_login_required import login_not_required

from .chat import (
    nearby_open_work,
    parse_report,
    reference_for,
    submit_report,
    work_item_for_reference,
)


@method_decorator(login_not_required, name="dispatch")
@method_decorator(ensure_csrf_cookie, name="dispatch")
class ReportChatView(TemplateView):
    """The home page: a chat that guides a resident through reporting a problem.

    Signed-in staff also see the triage panel that explains the suggested
    category, priority and team.
    """

    template_name = "intake/report_chat.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Show the staff triage panel to signed-in staff only."""
        context = super().get_context_data(**kwargs)
        context["show_staff_panel"] = self.request.user.is_staff
        return context


@method_decorator(login_not_required, name="dispatch")
class OldReportLinkView(RedirectView):
    """Send links to /report/ (where the chat used to be) to the home page."""

    pattern_name = "intake:form_intake"


@method_decorator(login_not_required, name="dispatch")
class CreateReportView(View):
    """Store a report from the chat and return its public reference."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> JsonResponse:
        """Create the work item and submission for one chat report."""
        try:
            work_item, _ = submit_report(parse_report(request.body))
        except ValidationError as error:
            return JsonResponse({"error": " ".join(error.messages)}, status=400)
        return JsonResponse(
            {"reference": reference_for(work_item), "status": work_item.status.label},
            status=201,
        )


@method_decorator(login_not_required, name="dispatch")
class ReportStatusView(View):
    """Return a report's status by public reference, without personal details."""

    http_method_names = ["get"]

    def get(self, request: HttpRequest, reference: str) -> JsonResponse:
        """Look up the work item behind a public reference."""
        work_item = work_item_for_reference(reference)
        if work_item is None:
            return JsonResponse({"error": "No report has that reference."}, status=404)
        return JsonResponse(
            {
                "reference": reference_for(work_item),
                "status": work_item.status.label,
                "issue": str(work_item.issue_type),
            }
        )


@method_decorator(login_not_required, name="dispatch")
class NearbyReportView(View):
    """Find an open job that may be the problem a resident is reporting.

    Used by the chat to ask "Is this the same problem?" before a duplicate
    work item is created. Returns only the public reference and its age.
    """

    http_method_names = ["get"]

    def get(self, request: HttpRequest) -> JsonResponse:
        """Return the nearest matching open work item, or no match."""
        work_item = nearby_open_work(
            request.GET.get("category", ""), request.GET.get("postcode", "")
        )
        if work_item is None:
            return JsonResponse({"match": None})
        return JsonResponse(
            {
                "match": {
                    "reference": reference_for(work_item),
                    "days_ago": (timezone.now() - work_item.created_at).days,
                    "status": work_item.status.label,
                }
            }
        )
