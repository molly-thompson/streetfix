"""Phone screens for officers doing the work on site."""

from typing import Any

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from . import field_work, geo, report_summary
from .forms import BeforePhotoForm, CommentForm
from .organisation_models import Employee
from .templatetags.fieldops import PRIORITY_COLOURS
from .visit_report import (
    CONFIRMATIONS,
    FURTHER_WORK_OUTCOMES,
    UNFINISHED_OUTCOMES,
    VisitReportForm,
)
from .work_models import WorkItem, WorkItemComment, WorkItemPhoto, WorkItemReport


class OfficerMixin(LoginRequiredMixin):
    """Restrict a view to signed-in employees and find their profile."""

    request: HttpRequest

    def employee(self) -> Employee:
        """Return the signed-in employee, or refuse access."""
        user = self.request.user
        employee = (
            Employee.objects.filter(user=user).select_related("department").first()
            if user.is_authenticated
            else None
        )
        if employee is None:
            raise PermissionDenied("Only employees can use the field app.")
        return employee

    def work_item(self, pk: int) -> WorkItem:
        """Return a work item the employee is currently on."""
        return get_object_or_404(
            WorkItem.objects.select_related(
                "issue_type__department", "priority", "urgency", "status"
            ).distinct(),
            pk=pk,
            assignments__employee=self.employee(),
            assignments__unassigned_at__isnull=True,
        )

    def page(self, template: str, context: dict[str, Any]) -> HttpResponse:
        """Render an officer page with what the header and tabs need."""
        return render(
            self.request,
            f"employees/officer/{template}",
            {"employee": self.employee(), **context},
        )


def _with_visit(item: WorkItem, employee: Employee) -> WorkItem:
    """Attach the officer's role, next step and the job's address."""
    report = field_work.draft_report(item, employee)
    arrived = report is not None and report.arrived_at is not None
    item.is_case_officer = field_work.is_case_officer(item, employee)  # type: ignore[attr-defined]
    item.next_step = (  # type: ignore[attr-defined]
        "in_progress"
        if item.status.code == "IN_PROGRESS"
        else "arrived"
        if arrived
        else "assigned"
    )
    item.address = geo.street_address(item)  # type: ignore[attr-defined]
    return item


def _day(employee: Employee) -> tuple[list[WorkItem], WorkItem | None, geo.DayPlan]:
    """Return the officer's jobs in route order, the current one and ETAs."""
    jobs = [_with_visit(item, employee) for item in field_work.my_work(employee)]
    current = next((j for j in jobs if j.next_step != "assigned"), None)  # type: ignore[attr-defined]
    if current is not None:
        jobs.remove(current)
        jobs.insert(0, current)
    plan = geo.plan_day(jobs, on_site=current)
    for job in jobs:
        job.leg = plan.legs.get(job.pk)  # type: ignore[attr-defined]
    return jobs, current, plan


def _map_points(jobs: list[WorkItem]) -> dict[str, Any]:
    """Return what the map script needs: the depot and each stop."""
    lat, lng = geo.depot()
    return {
        "depot": {"lat": lat, "lng": lng, "name": settings.FIELD_DEPOT["name"]},
        "tiles": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "stops": [
            {
                "lat": float(job.latitude),
                "lng": float(job.longitude),
                "title": job.issue_type.name,
                "address": job.address,  # type: ignore[attr-defined]
                "colour": PRIORITY_COLOURS.get(job.priority.code, "#64748b"),
                "url": reverse("employees:my_job", args=[job.pk]),
            }
            for job in jobs
        ],
    }


class MyJobsView(OfficerMixin, View):
    """The officer's day: current or next job, the rest, and what's done."""

    def get(self, request: HttpRequest) -> HttpResponse:
        """Show the officer's jobs as a list or on a map."""
        employee = self.employee()
        jobs, current, plan = _day(employee)
        hero = jobs[0] if jobs else None
        done = list(field_work.reported_today(employee))
        total = len(jobs) + len(done)
        show_map = request.GET.get("show") == "map"
        return self.page(
            "my_jobs.html",
            {
                "tab": "today",
                "hero": hero,
                "is_current": hero is not None and hero is current,
                "rest": jobs[1:],
                "remaining": len(jobs),
                "plan": plan,
                "done": done,
                "total": total,
                "progress": round(100 * len(done) / total) if total else 0,
                "show_map": show_map,
                "map_points": _map_points(jobs) if show_map else None,
            },
        )


class MapView(OfficerMixin, View):
    """All the officer's remaining stops on a map."""

    def get(self, request: HttpRequest) -> HttpResponse:
        """Show the route map."""
        jobs, _, _ = _day(self.employee())
        return self.page("map.html", {"tab": "map", "map_points": _map_points(jobs)})


class AlertsView(OfficerMixin, View):
    """Messages from managers on the officer's jobs."""

    def get(self, request: HttpRequest) -> HttpResponse:
        """List recent comments others have left on the officer's jobs."""
        employee = self.employee()
        alerts = (
            WorkItemComment.objects.filter(
                work_item__assignments__employee=employee,
                work_item__assignments__unassigned_at__isnull=True,
            )
            .exclude(author=employee)
            .select_related("author", "work_item__issue_type")
            .distinct()
            .order_by("-created_at")[:40]
        )
        return self.page("alerts.html", {"tab": "alerts", "alerts": alerts})


class JobView(OfficerMixin, View):
    """One job: details, next step, and comments to the manager."""

    def render_job(
        self, item: WorkItem, form: CommentForm | None = None
    ) -> HttpResponse:
        """Show the job page."""
        employee = self.employee()
        jobs, _, _ = _day(employee)
        planned = next((job for job in jobs if job.pk == item.pk), None)
        job = planned or _with_visit(item, employee)
        comments = list(item.comments.select_related("author"))
        submission = item.submissions.order_by("submitted_at").first()
        return self.page(
            "job.html",
            {
                "job": job,
                "leg": getattr(job, "leg", None),
                "on_site_minutes": geo.ON_SITE_MINUTES,
                "description": submission.description if submission else "",
                "from_management": [c for c in comments if c.author_id != employee.pk],
                "mine": [c for c in comments if c.author_id == employee.pk],
                "form": form or CommentForm(),
                "map_points": _map_points([job]),
            },
        )

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Show the job."""
        return self.render_job(self.work_item(pk))

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Add a comment, or record arriving on site."""
        item = self.work_item(pk)
        employee = self.employee()
        if "arrive" in request.POST:
            try:
                field_work.arrive(item, employee)
            except ValidationError as error:
                messages.error(request, " ".join(error.messages))
                return redirect("employees:my_job", pk=item.pk)
            return redirect("employees:before_photo", pk=item.pk)

        form = CommentForm(request.POST)
        if not form.is_valid():
            return self.render_job(item, form)
        field_work.add_comment(item, employee, form.cleaned_data["content"])
        messages.success(request, "Comment sent to your manager.")
        return redirect("employees:my_job", pk=item.pk)


class BeforePhotoView(OfficerMixin, View):
    """Photograph the site as found, then start work."""

    def visit(self, pk: int) -> WorkItemReport:
        """Return the visit's draft report, recording arrival if needed."""
        item = self.work_item(pk)
        try:
            return field_work.arrive(item, self.employee())
        except ValidationError as error:
            raise PermissionDenied(" ".join(error.messages)) from error

    def render_page(
        self, report: WorkItemReport, form: BeforePhotoForm | None = None
    ) -> HttpResponse:
        """Show the before photo step."""
        return self.page(
            "before_photo.html",
            {
                "job": _with_visit(report.work_item, self.employee()),
                "photos": report.photos.filter(tag=WorkItemPhoto.Tag.BEFORE),
                "form": form or BeforePhotoForm(),
                "min_reason": field_work.NO_PHOTO_REASON_MIN_LENGTH,
            },
        )

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Show the before photo step."""
        return self.render_page(self.visit(pk))

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Upload a before photo, or start work."""
        report = self.visit(pk)
        employee = self.employee()
        form = BeforePhotoForm(request.POST, request.FILES)
        if not form.is_valid():
            return self.render_page(report, form)
        if form.cleaned_data["photo"]:
            try:
                field_work.add_photo(
                    report,
                    form.cleaned_data["photo"],
                    tag=WorkItemPhoto.Tag.BEFORE,
                    employee=employee,
                )
            except ValidationError as error:
                form.add_error("photo", error)
                return self.render_page(report, form)
        if "start" not in request.POST:
            return redirect("employees:before_photo", pk=report.work_item_id)
        try:
            field_work.start_work(
                report,
                employee,
                no_photo_reason=form.cleaned_data["no_photo_reason"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.render_page(report, form)
        messages.success(request, "Before photo saved — work started.")
        return redirect("employees:my_job", pk=report.work_item_id)


class VisitReportView(OfficerMixin, View):
    """The completion report, saved as a draft every time it is sent."""

    def visit(self, pk: int) -> WorkItemReport:
        """Return the draft report for work that has started."""
        item = self.work_item(pk)
        report = field_work.draft_report(item, self.employee())
        if item.status.code != "IN_PROGRESS" or report is None:
            raise PermissionDenied("Start the work before reporting on it.")
        return report

    def render_page(
        self,
        report: WorkItemReport,
        form: VisitReportForm | None = None,
        errors: list[str] | None = None,
    ) -> HttpResponse:
        """Show the report form."""
        form = form or VisitReportForm(instance=report)
        return self.page(
            "report.html",
            {
                "job": _with_visit(report.work_item, self.employee()),
                "report": report,
                "form": form,
                "outcomes": WorkItemReport.Outcome.choices,
                "further_outcomes": [str(value) for value in FURTHER_WORK_OUTCOMES],
                "unfinished_outcomes": [str(value) for value in UNFINISHED_OUTCOMES],
                "confirmations": [
                    (name, label, form[name].value()) for name, label in CONFIRMATIONS
                ],
                "photos": report.photos.all(),
                "has_before_photo": report.has_before_photo(),
                "errors": errors or [],
            },
        )

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Show the report form."""
        return self.render_page(self.visit(pk))

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Save the draft, add a photo, or submit the report."""
        report = self.visit(pk)
        employee = self.employee()
        form = VisitReportForm(request.POST, request.FILES, instance=report)
        if not form.is_valid():
            return self.render_page(report, form)
        report = form.save()
        if form.cleaned_data["photo"]:
            try:
                field_work.add_photo(
                    report,
                    form.cleaned_data["photo"],
                    tag=(
                        WorkItemPhoto.Tag.BEFORE
                        if request.POST.get("photo_tag") == WorkItemPhoto.Tag.BEFORE
                        else WorkItemPhoto.Tag.AFTER
                    ),
                    employee=employee,
                )
            except ValidationError as error:
                return self.render_page(report, form, error.messages)
        if "finish" not in request.POST:
            return redirect("employees:visit_report", pk=report.work_item_id)
        problems = form.problems(report) or list(report.submission_errors().values())
        if problems:
            return self.render_page(report, form, problems)
        # Write the case note and let the officer check it before submitting.
        report.ai_summary = report_summary.plain_summary(report)
        report.save(update_fields=("ai_summary",))
        request.session[_summary_key(report)] = True
        return redirect("employees:visit_summary", pk=report.work_item_id)


def _summary_key(report: WorkItemReport) -> str:
    return f"visit_summary_{report.pk}"


class VisitSummaryView(VisitReportView):
    """The officer checks the drafted case note, then approves and submits."""

    def render_summary(
        self, report: WorkItemReport, text: str, errors: list[str]
    ) -> HttpResponse:
        """Show the drafted summary for checking."""
        return self.page(
            "summary.html",
            {
                "job": _with_visit(report.work_item, self.employee()),
                "report": report,
                "text": text,
                "errors": errors,
            },
        )

    def drafted(self, report: WorkItemReport) -> bool:
        """Return whether the officer has been given a summary to check."""
        return bool(
            self.request.session.get(_summary_key(report)) and report.ai_summary
        )

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Show the drafted summary."""
        report = self.visit(pk)
        if not self.drafted(report):
            return redirect("employees:visit_report", pk=pk)
        return self.render_summary(report, report.ai_summary, [])

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Approve the summary and submit the report."""
        report = self.visit(pk)
        if not self.drafted(report):
            return redirect("employees:visit_report", pk=pk)
        text = request.POST.get("summary", "")
        try:
            field_work.submit_report_with_summary(report, self.employee(), text)
        except ValidationError as error:
            return self.render_summary(report, text, error.messages)
        request.session.pop(_summary_key(report), None)
        messages.success(request, "Report submitted.")
        return redirect("employees:my_jobs")
