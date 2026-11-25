"""Views for the intake application.

The public report chat is the site's home page; the JSON views behind it
create reports, look up their status and find possible duplicates.
"""

import logging
from typing import Any
from uuid import UUID

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Count, OuterRef, Q, QuerySet, Subquery
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.http.response import HttpResponseBase
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
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

from employees.organisation_models import Employee, IssueType
from employees.work_models import WorkItem
from intake.forms import (
    AcceptReportForm,
    DuplicateConfirmationForm,
    DuplicateLookupForm,
    LocationCorrectionForm,
    OutOfScopeForm,
    ReopenReportForm,
)
from intake.models import (
    IssueCategory,
    ReportPhotoSlot,
    ReportSubmission,
    SlaPolicy,
    TriageEngineJob,
)
from intake.report_views import session_key
from intake.services.acceptance import accept_report
from intake.services.duplicates import duplicate_candidates, link_duplicate
from intake.services.map_config import public_map_config
from intake.services.matching import assess_duplicates, current_assessments
from intake.services.photo_delivery import PhotoUnavailableError, open_report_photo
from intake.services.photo_upload import photo_upload_enabled
from intake.services.queue import pending_reviews
from intake.services.rate_limit import (
    RATE_LIMITED,
    REPORT_SUBMISSION,
    client_address,
    reserve,
)
from intake.services.reference import (
    display_reference,
    public_status,
    reference_for_work_item,
    submission_for_reference,
)
from intake.services.review import (
    correct_location,
    recover_received,
    reject_out_of_scope,
    reopen_final_decision,
)
from site_settings.configuration import get_site_configuration
from intake.services.triage.engine import (
    engine_mode,
    request_assessment,
    reviewable_result,
)

from .chat import (
    nearby_open_work,
    parse_issue_type_id,
    parse_report,
    submit_chat_report,
)

logger = logging.getLogger(__name__)

# Placeholder IDs in the photo verify URL; the chat fills in the real ones.
ZERO_ID = UUID(int=0)


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
        context["report_form_enabled"] = settings.INTAKE_PUBLIC_REPORTING_ENABLED
        categories = {
            category.issue_type_id: category
            for category in IssueCategory.objects.filter(
                active=True, issue_type__isnull=False
            ).prefetch_related("subcategories", "keywords")
        }
        issues = (
            IssueType.objects.filter(
                active=True, kind=IssueType.Kind.ISSUE, department__isnull=False
            )
            .select_related("department")
            .order_by("sort_order", "name", "pk")
        )
        priority_names = {
            "CRITICAL": "Urgent",
            "HIGH": "High",
            "NORMAL": "Medium",
            "LOW": "Low",
        }
        issue_options = []
        for issue in issues:
            if issue.department is None:
                raise ValueError(f"Issue type {issue.pk} has no department.")
            category = categories.get(issue.pk)
            if category and category.default_priority_code not in ("", *priority_names):
                logger.warning(
                    "Chat category %s has an unsupported default priority %s.",
                    category.pk,
                    category.default_priority_code,
                )
            if category:
                for subcategory in category.subcategories.all():
                    if subcategory.active and subcategory.raised_priority_code not in (
                        "",
                        *priority_names,
                    ):
                        logger.warning(
                            "Chat subcategory %s has unsupported raised priority %s.",
                            subcategory.pk,
                            subcategory.raised_priority_code,
                        )
            issue_options.append(
                {
                    "id": issue.pk,
                    "name": issue.name,
                    "team": issue.department.name,
                    "translationCode": category.code if category else "",
                    "priority": priority_names.get(
                        category.default_priority_code, "Medium"
                    )
                    if category
                    else "Medium",
                    "keywords": [
                        keyword.pattern
                        for keyword in category.keywords.all()
                        if keyword.active
                    ]
                    if category
                    else [],
                    "subissues": [
                        {
                            "label": subcategory.label,
                            "translationCode": subcategory.code,
                            "raise": priority_names.get(
                                subcategory.raised_priority_code
                            ),
                        }
                        for subcategory in category.subcategories.all()
                        if subcategory.active
                    ]
                    if category
                    else [],
                }
            )
        slas = {}
        for policy in SlaPolicy.objects.filter(active=True).order_by("-priority_code"):
            # The original SLA seed used URGENT for the CRITICAL priority.
            code = (
                "CRITICAL" if policy.priority_code == "URGENT" else policy.priority_code
            )
            if code not in priority_names:
                logger.warning(
                    "SLA policy %s has an unsupported priority code.", policy.pk
                )
                continue
            if priority_names[code] in slas:
                logger.warning(
                    "Multiple active SLA policies map to %s; using %s.",
                    priority_names[code],
                    policy.priority_code,
                )
            slas[priority_names[code]] = {
                "ackH": policy.acknowledgement_hours,
                "resD": policy.resolution_working_days,
            }
        context["chat_config"] = {
            "map": public_map_config(),
            "photos": settings.INTAKE_PUBLIC_REPORTING_ENABLED
            and photo_upload_enabled(),
            "photoAuthorizeUrl": reverse("intake:photo_authorize"),
            "photoVerifyUrl": reverse("intake:photo_verify", args=[ZERO_ID, ZERO_ID]),
            "issueTypes": issue_options,
            "slas": slas,
        }
        return context


@method_decorator(login_not_required, name="dispatch")
class OldReportLinkView(RedirectView):
    """Send links to /report/ (where the chat used to be) to the home page."""

    pattern_name = "intake:form_intake"


@method_decorator(login_not_required, name="dispatch")
class CreateReportView(View):
    """Save a report from the chat for review and return its public reference."""

    http_method_names = ["post"]

    def post(self, request: HttpRequest) -> JsonResponse:
        """Limit submissions per address, then record one chat report."""
        try:
            report = parse_report(request.body)
            reserve(REPORT_SUBMISSION, client_address(request))
            submission = submit_chat_report(report, session_key=session_key(request))
        except ValidationError as error:
            status = 429 if error.code == RATE_LIMITED else 400
            return JsonResponse({"error": " ".join(error.messages)}, status=status)
        return JsonResponse(
            {
                "reference": display_reference(submission),
                "status": public_status(submission),
            },
            status=201,
        )


@method_decorator(login_not_required, name="dispatch")
class ReportStatusView(View):
    """Return a report's status by public reference, without personal details."""

    http_method_names = ["get"]

    def get(self, request: HttpRequest, reference: str) -> JsonResponse:
        """Look up the report behind a public reference."""
        submission = submission_for_reference(reference)
        if submission is None:
            return JsonResponse({"error": "No report has that reference."}, status=404)
        return JsonResponse(
            {
                "reference": display_reference(submission),
                "status": public_status(submission),
                "issue": str(submission.reported_issue_type or ""),
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
        raw_issue_id = request.GET.get("issue_type_id")
        try:
            issue_type_id = (
                parse_issue_type_id(raw_issue_id) if raw_issue_id is not None else None
            )
        except ValidationError:
            return JsonResponse(
                {"error": "The issue type was not recognised."}, status=400
            )
        work_item = nearby_open_work(
            request.GET.get("category", ""),
            request.GET.get("postcode", ""),
            issue_type_id=issue_type_id,
        )
        reference = reference_for_work_item(work_item) if work_item else None
        if work_item is None or reference is None:
            return JsonResponse({"match": None})
        return JsonResponse(
            {
                "match": {
                    "reference": reference,
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
class ReportPhotoView(LoginRequiredMixin, View):
    """Stream an attached photo to reviewers or assigned employees."""

    def get(self, request: HttpRequest, slot_id: Any) -> HttpResponseBase:
        """Proxy the authenticated original without returning its provider URL."""
        user_id = request.user.pk
        if user_id is None:
            raise PermissionDenied
        employee = Employee.objects.filter(user_id=user_id).first()
        if employee is None:
            raise PermissionDenied
        slots = ReportPhotoSlot.objects.filter(
            draft__submission__isnull=False,
            asset_id__isnull=False,
        )
        if not request.user.has_perm("intake.review_reportsubmission"):
            slots = slots.filter(
                draft__submission__work_item__assignments__employee=employee,
                draft__submission__work_item__assignments__unassigned_at__isnull=True,
            )
        slot = get_object_or_404(slots, pk=slot_id)
        try:
            photo = open_report_photo(slot)
        except PhotoUnavailableError:
            return HttpResponse("Photo is temporarily unavailable.", status=502)
        content_types = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "webp": "image/webp",
            "heic": "image/heic",
        }
        response = StreamingHttpResponse(photo, content_type=content_types[slot.format])
        response["Content-Length"] = str(slot.size_bytes)
        disposition = "attachment" if slot.format == "heic" else "inline"
        response["Content-Disposition"] = (
            f'{disposition}; filename="report-photo.{slot.format}"'
        )
        response["X-Content-Type-Options"] = "nosniff"
        response["Content-Security-Policy"] = "default-src 'none'; sandbox"
        return response


@method_decorator(never_cache, name="dispatch")
class ReviewQueueView(ReviewerMixin, ListView):  # type: ignore[type-arg]
    """Display pending and recoverable intake reports."""

    template_name = "intake/review_queue.html"
    context_object_name = "submissions"
    paginate_by = 50

    def get_queryset(self) -> QuerySet[ReportSubmission]:
        """Order urgent reports first, then oldest first."""
        latest_job = TriageEngineJob.objects.filter(
            submission_id=OuterRef("pk")
        ).order_by("-created_at", "-pk")
        return pending_reviews().annotate(
            engine_job_status=Subquery(latest_job.values("status")[:1])
        )

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Summarize the full queue, not just the current page."""
        context = super().get_context_data(**kwargs)
        context["queue_totals"] = pending_reviews().aggregate(
            total=Count("pk"),
            urgent=Count("pk", filter=Q(queue_urgent=True)),
            processing=Count("pk", filter=Q(triage_state="RECEIVED")),
        )
        context["engine_mode"] = engine_mode()
        return context

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Summarize the full queue, not just the current page."""
        context = super().get_context_data(**kwargs)
        context["queue_counts"] = self.get_queryset().aggregate(
            total=Count("pk"),
            urgent=Count("pk", filter=Q(queue_urgent=True)),
            processing=Count("pk", filter=Q(triage_state="RECEIVED")),
            ready=Count("pk", filter=Q(triage_state="NEEDS_REVIEW")),
        )
        return context


def review_dashboard_context(submission: ReportSubmission) -> dict[str, Any]:
    """Provide candidate work and any current advisory results."""
    search = duplicate_candidates(submission)
    assessments: dict[int, dict[str, Any]] = {}
    matching_message = ""
    matching_enabled = (
        get_site_configuration().duplicate_matching_enabled
        and submission.triage_state == ReportSubmission.TriageState.NEEDS_REVIEW
    )
    if matching_enabled:
        try:
            assessments, matching_message = current_assessments(submission, search)
        except Exception:
            logger.exception("Could not load matching assessment for %s", submission.pk)
            matching_message = "Matching is unavailable. Use the existing work search."
    return {
        "duplicate_search": search,
        "matching_enabled": matching_enabled,
        "matching_message": matching_message,
        "matching_candidates": [
            {"candidate": candidate, "assessment": assessments.get(candidate.work.pk)}
            for candidate in search.candidates
        ],
        "report_photos": ReportPhotoSlot.objects.filter(
            draft__submission=submission, asset_id__isnull=False
        ).order_by("created_at", "pk"),
    }


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
        context.update(review_dashboard_context(self.object))
        context["duplicate_search"] = duplicate_candidates(self.object)
        context["report_photos"] = ReportPhotoSlot.objects.filter(
            draft__submission=self.object, asset_id__isnull=False
        ).order_by("created_at", "pk")
        context["engine_mode"] = engine_mode()
        job = self.object.engine_jobs.first()
        context["engine_job"] = job
        if job is not None and reviewable_result(job, self.object):
            context["engine_result_job"] = job
        return context


@method_decorator(never_cache, name="dispatch")
class AssessDuplicatesView(ReviewerMixin, View):
    """Run an explicit advisory assessment for a report in review."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Record the assessment or explain why it could not be run."""
        if not get_site_configuration().duplicate_matching_enabled:
            raise PermissionDenied
        submission = get_object_or_404(
            pending_reviews(),
            pk=pk,
            triage_state=ReportSubmission.TriageState.NEEDS_REVIEW,
        )
        reviewer = get_object_or_404(Employee, user_id=request.user.pk)
        try:
            assess_duplicates(submission.pk, reviewer=reviewer)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        except Exception:
            logger.exception("Could not assess duplicate matches for %s", submission.pk)
            messages.error(
                request,
                "Matching could not be completed. Use the existing work search.",
            )
        else:
            messages.success(request, "Advisory matching assessment completed.")
        return redirect("intake:review_detail", pk=submission.pk)
class RequestEngineAssessmentView(ReviewerMixin, View):
    """Queue an optional engine assessment for an authorized reviewer."""

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Schedule analysis without delaying review or contacting the provider."""
        submission = get_object_or_404(pending_reviews(), pk=pk)
        reviewer = get_object_or_404(Employee, user_id=request.user.pk)
        try:
            request_assessment(submission.pk, reviewer)
        except ValidationError as exc:
            messages.error(request, "; ".join(exc.messages))
        else:
            messages.success(request, "Assessment queued for processing.")
        return redirect("intake:review_detail", pk=pk)


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
                **review_dashboard_context(submission),
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
