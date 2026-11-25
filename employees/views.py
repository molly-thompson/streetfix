"""Views for the employees application.

This module contains views for employee management,
dashboards, and related functionality.
"""

from typing import Any

from django.contrib import messages
from django.contrib.auth.mixins import PermissionRequiredMixin
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.auth.views import LoginView
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import TemplateView

from intake.services.queue import pending_reviews

from . import approval, geo
from .dispatch import assign_work, dispatchable_work, remove_from_work
from .forms import AssignWorkForm, RemoveFromWorkForm
from .organisation_models import Employee
from .overview import (
    STAGE_FILTERS,
    job_flow,
    needs_attention,
    needs_case_officer_count,
    status_label,
    urgent_heading,
    urgent_unassigned,
    workforce,
)
from .work_models import WorkAssignment, WorkItem


def home_url(user: User | AnonymousUser) -> str | None:
    """Return where a user should land after signing in, if they have a home.

    Managers go to the operations overview and officers to their jobs.
    Administrators who are not employees go to the site admin. Anyone else
    has no particular home, so callers use their own default.
    """
    is_employee = user.is_authenticated and Employee.objects.filter(user=user).exists()
    if is_employee and user.has_perm("employees.add_workassignment"):
        return reverse("employees:dashboard")
    if is_employee:
        return reverse("employees:my_jobs")
    if user.is_staff:
        return reverse("admin:index")
    return None


class SignInView(LoginView):
    """Sign employees in; managers land on the operations overview."""

    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_default_redirect_url(self) -> str:
        """Send managers to the overview and officers to their jobs."""
        return home_url(self.request.user) or reverse("intake:form_intake")

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Use the site's branding name rather than the host name."""
        context = super().get_context_data(**kwargs)
        context.pop("site_name", None)
        return context


class ManagerMixin(PermissionRequiredMixin):
    """Restrict a view to managers: employees allowed to assign work."""

    permission_required = "employees.add_workassignment"
    request: HttpRequest

    def manager(self) -> Employee:
        """Return the signed-in employee, or refuse access."""
        user = self.request.user
        employee = (
            Employee.objects.filter(user=user).first()
            if user.is_authenticated
            else None
        )
        if employee is None:
            raise PermissionDenied("Only employees can manage work.")
        return employee

    def shell_context(self, active: str) -> dict[str, Any]:
        """Return what the manager layout's sidebar needs."""
        can_review = self.request.user.has_perm("intake.review_reportsubmission")
        return {
            "active": active,
            "needs_case_officer": needs_case_officer_count(self.manager().department),
            "can_review_reports": can_review,
            "reports_awaiting_review": pending_reviews().count() if can_review else 0,
        }


class EmployeeDashboardView(ManagerMixin, TemplateView):
    """The manager's operations overview for their department.

    Shows the job flow from triage to closure, who is working on what,
    and the exceptions that need the manager's attention.
    """

    template_name = "employees/dashboard.html"

    def handle_no_permission(self) -> HttpResponseRedirect:
        """Send signed-in staff who are not managers to their own page.

        /employees/ is where the site's Employees link and sign-in lead, so
        officers arriving here are taken to their jobs instead of an error.
        """
        if self.request.user.is_authenticated:
            home = home_url(self.request.user)
            if home and home != self.request.path:
                return redirect(home)
        return super().handle_no_permission()

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Gather the department's figures."""
        context = super().get_context_data(**kwargs)
        department = self.manager().department
        attention = needs_attention(department)
        rows = workforce(department)
        context.update(
            self.shell_context("overview"),
            department=department,
            urgent=urgent_unassigned(department),
            urgent_heading=urgent_heading(),
            flow=job_flow(department),
            attention=attention,
            attention_total=sum(stage.count for stage in attention),
            workforce=rows,
            working=sum(1 for row in rows if row.working_on is not None),
        )
        return context


class DispatchListView(ManagerMixin, TemplateView):
    """Department work that needs a case officer, and work already assigned."""

    template_name = "employees/dispatch_list.html"

    def get_context_data(self, **kwargs: Any) -> dict[str, Any]:
        """Split the department's work into unassigned and assigned."""
        context = super().get_context_data(**kwargs)
        dispatcher = self.manager()
        stage = self.request.GET.get("stage", "")
        work_items = dispatchable_work(dispatcher.department)
        if stage in STAGE_FILTERS:
            work_items = work_items.filter(status__code__in=STAGE_FILTERS[stage])
        else:
            stage = ""
        work = list(work_items)
        case_officers = {
            row.work_item_id: row.employee
            for row in WorkAssignment.objects.filter(
                work_item__in=work,
                is_case_officer=True,
                unassigned_at__isnull=True,
            ).select_related("employee")
        }
        for item in work:
            item.case_officer = case_officers.get(item.pk)  # type: ignore[attr-defined]
        context.update(
            self.shell_context("dispatch"),
            department=dispatcher.department,
            unassigned=[item for item in work if not item.has_case_officer],  # type: ignore[attr-defined]
            assigned=[item for item in work if item.has_case_officer],  # type: ignore[attr-defined]
            assigned_label=status_label("ASSIGNED"),
            stage=stage,
            stage_items=work,
            stage_label=(
                "Paused" if stage == "paused" else status_label(stage.upper())
            ),
        )
        return context


class DispatchDetailView(ManagerMixin, View):
    """Assign, reassign or remove people on one work item."""

    template_name = "employees/dispatch_detail.html"

    def work_item(self, pk: int) -> WorkItem:
        """Return the work item if it belongs to the dispatcher's department."""
        return get_object_or_404(
            WorkItem.objects.select_related(
                "issue_type", "priority", "urgency", "status"
            ),
            pk=pk,
            issue_type__department=self.manager().department,
        )

    def render(
        self,
        work_item: WorkItem,
        form: AssignWorkForm | None = None,
        review_error: str = "",
    ) -> HttpResponse:
        """Show the work item, its team, the assign form and the history."""
        assignments = work_item.assignments.select_related("employee", "assigned_by")
        current = [row for row in assignments if row.is_open]
        report = approval.latest_report(work_item)
        awaiting_approval = report is not None and work_item.status.is_awaiting_review
        return render(
            self.request,
            self.template_name,
            {
                **self.shell_context("dispatch"),
                "work_item": work_item,
                "current": current,
                "has_case_officer": any(row.is_case_officer for row in current),
                "support_count": sum(not row.is_case_officer for row in current),
                "history": list(assignments.order_by("-assigned_at", "-pk")),
                "form": form or AssignWorkForm(work_item=work_item),
                "can_assign": not work_item.status.is_not_yet_triaged,
                "address": geo.street_address(work_item),
                "report": report,
                "awaiting_approval": awaiting_approval,
                "review_error": review_error,
            },
        )

    def get(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Show the dispatch page for a work item."""
        return self.render(self.work_item(pk))

    def post(self, request: HttpRequest, pk: int) -> HttpResponse:
        """Handle assigning someone or taking them off the work item."""
        work_item = self.work_item(pk)
        if "remove" in request.POST:
            return self.remove(work_item)
        if "approve" in request.POST or "send_back" in request.POST:
            return self.review(work_item)

        form = AssignWorkForm(request.POST, work_item=work_item)
        if not form.is_valid():
            return self.render(work_item, form)
        employee = form.cleaned_data["employee"]
        try:
            assign_work(
                work_item,
                employee,
                case_officer=form.as_case_officer,
                dispatcher=self.manager(),
                reason=form.cleaned_data["reason"],
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.render(work_item, form)
        role = "case officer" if form.as_case_officer else "support"
        messages.success(request, f"{employee} is now {role} on this job.")
        return redirect("employees:dispatch_detail", pk=work_item.pk)

    def remove(self, work_item: WorkItem) -> HttpResponse:
        """Take one person off the work item."""
        form = RemoveFromWorkForm(self.request.POST)
        if form.is_valid():
            assignment = get_object_or_404(
                WorkAssignment,
                pk=form.cleaned_data["assignment"],
                work_item=work_item,
                unassigned_at__isnull=True,
            )
            remove_from_work(
                assignment,
                dispatcher=self.manager(),
                reason=form.cleaned_data["reason"],
            )
            messages.success(self.request, f"{assignment.employee} removed from job.")
        return redirect("employees:dispatch_detail", pk=work_item.pk)

    def review(self, work_item: WorkItem) -> HttpResponse:
        """Approve the officer's report and close the job, or send it back."""
        note = self.request.POST.get("note", "")
        try:
            if "approve" in self.request.POST:
                approval.approve(work_item, self.manager(), note=note)
                messages.success(self.request, "Job approved and closed.")
                return redirect("employees:dispatch")
            approval.send_back(work_item, self.manager(), note=note)
        except ValidationError as error:
            return self.render(work_item, review_error=" ".join(error.messages))
        messages.success(self.request, "Report sent back to the case officer.")
        return redirect("employees:dispatch_detail", pk=work_item.pk)
