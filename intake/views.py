"""Views for the intake application.

The public report chat is the site's home page; the JSON views behind it
create reports, look up their status and find possible duplicates.
"""

import logging
from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import (
    DetailView,
    FormView,
    ListView,
    RedirectView,
    TemplateView,
)
from global_login_required import login_not_required

from employees.organisation_models import Employee
from employees.work_models import WorkItem
from intake.forms import (
    AcceptReportForm,
    DuplicateConfirmationForm,
    DuplicateLookupForm,
    LocationCorrectionForm,
    OutOfScopeForm,
    ReopenReportForm,
)
from intake.models import ReportSubmission
from intake.services.acceptance import accept_report
from intake.services.duplicates import duplicate_candidates, link_duplicate
from intake.services.queue import pending_reviews
from intake.services.review import (
    correct_location,
    recover_received,
    reject_out_of_scope,
    reopen_final_decision,
)

from .chat import (
    nearby_open_work,
    parse_report,
    reference_for,
    submit_report,
    work_item_for_reference,
)

logger = logging.getLogger(__name__)


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


class ReviewerMixin(PermissionRequiredMixin):
    """Require both review permission and an employee identity."""

    permission_required = "intake.review_reportsubmission"
    request: HttpRequest

    def has_permission(self) -> bool:
        """Only authorized employees can access the review interface."""
        user_id = self.request.user.pk
        return (
            super().has_permission()
            and user_id is not None
            and Employee.objects.filter(user_id=user_id).exists()
        )


@method_decorator(never_cache, name="dispatch")
class ReviewQueueView(ReviewerMixin, ListView):  # type: ignore[type-arg]
    """Display pending and recoverable intake reports."""

    template_name = "intake/review_queue.html"
    context_object_name = "submissions"
    paginate_by = 50

    def get_queryset(self) -> QuerySet[ReportSubmission]:
        """Order urgent reports first, then oldest first."""
        return pending_reviews()


def finalized_reports() -> QuerySet[ReportSubmission]:
    """Find final decisions that can be reopened without changing work."""
    return ReportSubmission.objects.filter(
        triage_state__in=(
            ReportSubmission.TriageState.OUT_OF_SCOPE,
            ReportSubmission.TriageState.DUPLICATE,
        )
    )


@method_decorator(never_cache, name="dispatch")
class FinalizedReportListView(ReviewerMixin, ListView):  # type: ignore[type-arg]
    """List rejected and duplicate reports for possible correction."""

    template_name = "intake/finalized_reports.html"
    context_object_name = "submissions"
    paginate_by = 50

    def get_queryset(self) -> QuerySet[ReportSubmission]:
        """Return recent final decisions in a stable order."""
        return finalized_reports().order_by("-submitted_at", "-pk")


@method_decorator(never_cache, name="dispatch")
class ReopenReportView(ReviewerMixin, FormView):  # type: ignore[type-arg]
    """Review a final decision and return it to the central queue."""

    form_class = ReopenReportForm
    template_name = "intake/reopen_report.html"

    def get_submission(self) -> ReportSubmission:
        """Load an eligible report with its decision history."""
        if not hasattr(self, "_submission"):
            self._submission = get_object_or_404(
                finalized_reports().prefetch_related("triage_attempts__reviewer"),
                pk=self.kwargs["pk"],
            )
        return self._submission

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Show the prior decision before requesting confirmation."""
        return {
            **super().get_context_data(**kwargs),
            "submission": self.get_submission(),
        }

    def form_valid(self, form: ReopenReportForm) -> HttpResponse:
        """Audit the correction and return the report to review."""
        submission = self.get_submission()
        reviewer = get_object_or_404(Employee, user_id=self.request.user.pk)
        try:
            reopen_final_decision(
                submission.pk, reviewer=reviewer, reason=form.cleaned_data["reason"]
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, "Report reopened for review.")
        return redirect("intake:review_detail", pk=submission.pk)


@method_decorator(never_cache, name="dispatch")
class ReviewDetailView(ReviewerMixin, DetailView):  # type: ignore[type-arg]
    """Show the evidence and audit history for a report awaiting review."""

    template_name = "intake/review_detail.html"
    context_object_name = "submission"

    def get_queryset(self) -> QuerySet[ReportSubmission]:
        """Only reports awaiting review or recovery are accessible here."""
        return (
            pending_reviews()
            .select_related("reporter", "contact_method")
            .prefetch_related("triage_attempts__reviewer")
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Provide the location correction form for reports in review."""
        context = super().get_context_data(**kwargs)
        context["location_form"] = LocationCorrectionForm(
            initial={
                "latitude": self.object.latitude,
                "longitude": self.object.longitude,
            }
        )
        context["duplicate_search"] = duplicate_candidates(self.object)
        return context


@method_decorator(never_cache, name="dispatch")
class CorrectLocationView(ReviewerMixin, View):
    """Allow a reviewer to correct a report's map pin."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Validate and audit a location correction."""
        submission = get_object_or_404(pending_reviews(), pk=pk)
        reviewer = get_object_or_404(Employee, user_id=request.user.pk)
        form = LocationCorrectionForm(request.POST)
        if form.is_valid():
            try:
                correct_location(
                    submission.pk,
                    reviewer=reviewer,
                    latitude=form.cleaned_data["latitude"],
                    longitude=form.cleaned_data["longitude"],
                    reason=form.cleaned_data["reason"],
                )
            except ValidationError as exc:
                form.add_error(None, exc)
            else:
                messages.success(request, "Location saved.")
                return redirect("intake:review_detail", pk=submission.pk)
        return render(
            request,
            "intake/review_detail.html",
            {
                "submission": submission,
                "location_form": form,
                "duplicate_search": duplicate_candidates(submission),
            },
            status=400,
        )


@method_decorator(never_cache, name="dispatch")
class RecoverReportView(ReviewerMixin, View):
    """Allow a reviewer to retry triage for a stalled submission."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Retry processing without discarding the original report."""
        submission = get_object_or_404(pending_reviews(), pk=pk)
        reviewer = get_object_or_404(Employee, user_id=request.user.pk)
        try:
            recover_received(submission.pk, reviewer=reviewer)
        except Exception:
            logger.exception("Could not recover submission %s", submission.pk)
            messages.error(
                request, "Triage could not be retried. The report remains in the queue."
            )
        else:
            messages.success(
                request, "Triage processing completed. The report remains for review."
            )
        return redirect("intake:review_detail", pk=submission.pk)


@method_decorator(never_cache, name="dispatch")
class OutOfScopeView(ReviewerMixin, FormView):  # type: ignore[type-arg]
    """Record a human decision that a report is outside the deployment's scope."""

    form_class = OutOfScopeForm
    template_name = "intake/out_of_scope.html"

    def get_submission(self) -> ReportSubmission:
        """Return the report still awaiting review."""
        return get_object_or_404(
            pending_reviews(),
            pk=self.kwargs["pk"],
            triage_state=ReportSubmission.TriageState.NEEDS_REVIEW,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Include the report being reviewed."""
        return {
            **super().get_context_data(**kwargs),
            "submission": self.get_submission(),
        }

    def form_valid(self, form: OutOfScopeForm) -> HttpResponse:
        """Record the decision and return to the queue."""
        submission = self.get_submission()
        reviewer = get_object_or_404(Employee, user_id=self.request.user.pk)
        try:
            reject_out_of_scope(
                submission.pk, reviewer=reviewer, reason=form.cleaned_data["reason"]
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, "Report marked out of scope.")
        return redirect("intake:review_queue")


@method_decorator(never_cache, name="dispatch")
class DuplicateReviewView(ReviewerMixin, FormView):  # type: ignore[type-arg]
    """Preview work and confirm a human duplicate decision."""

    form_class = DuplicateConfirmationForm
    template_name = "intake/duplicate_review.html"

    def get_submission(self) -> ReportSubmission:
        """Return the report still awaiting review."""
        return get_object_or_404(
            pending_reviews(),
            pk=self.kwargs["pk"],
            triage_state=ReportSubmission.TriageState.NEEDS_REVIEW,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Show the selected work item's current status before confirmation."""
        context = super().get_context_data(**kwargs)
        lookup_data = (
            self.request.POST if self.request.method == "POST" else self.request.GET
        )
        lookup = DuplicateLookupForm(lookup_data or None)
        work = None
        if lookup.is_valid():
            work = (
                WorkItem.objects.select_related(
                    "status", "issue_type", "issue_type__department"
                )
                .filter(pk=lookup.cleaned_data["work_item_id"])
                .first()
            )
        context.update(submission=self.get_submission(), lookup=lookup, work=work)
        if work is not None:
            context["related_reports"] = work.submissions.only("description").order_by(
                "pk"
            )[:5]
        if self.request.method == "GET" and work is not None:
            context["form"] = self.get_form_class()(initial={"work_item_id": work.pk})
        return context

    def form_valid(self, form: DuplicateConfirmationForm) -> HttpResponse:
        """Commit a reviewer-confirmed duplicate link."""
        submission = self.get_submission()
        reviewer = get_object_or_404(Employee, user_id=self.request.user.pk)
        try:
            link_duplicate(
                submission.pk,
                reviewer=reviewer,
                work_item_id=form.cleaned_data["work_item_id"],
                reason=form.cleaned_data["reason"],
                confirmed_not_recurrence=form.cleaned_data["confirmed_not_recurrence"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, "Report linked to existing work.")
        return redirect("intake:review_queue")


@method_decorator(never_cache, name="dispatch")
class AcceptReportView(ReviewerMixin, FormView):  # type: ignore[type-arg]
    """Make explicit human decisions and create operational work."""

    form_class = AcceptReportForm
    template_name = "intake/accept_report.html"

    def get_submission(self) -> ReportSubmission:
        """Return the report still awaiting review."""
        return get_object_or_404(
            pending_reviews(),
            pk=self.kwargs["pk"],
            triage_state=ReportSubmission.TriageState.NEEDS_REVIEW,
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Include the report being reviewed."""
        return {
            **super().get_context_data(**kwargs),
            "submission": self.get_submission(),
        }

    def form_valid(self, form: AcceptReportForm) -> HttpResponse:
        """Create triaged work only after all confirmations."""
        submission = self.get_submission()
        reviewer = get_object_or_404(Employee, user_id=self.request.user.pk)
        data = form.cleaned_data
        try:
            work = accept_report(
                submission.pk,
                reviewer=reviewer,
                issue_type_id=data["issue_type"].pk,
                priority_code=data["priority"].code,
                urgency_code=data["urgency"].code,
                scope_confirmed=data["scope_confirmed"],
                not_duplicate_confirmed=data["not_duplicate_confirmed"],
                location_confirmed=data["location_confirmed"],
                reason=data["reason"],
            )
        except ValidationError as exc:
            form.add_error(None, exc)
            return self.form_invalid(form)
        messages.success(self.request, f"Report accepted as work item {work.pk}.")
        return redirect("intake:review_queue")
