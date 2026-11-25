"""Views for the analytics application.

This module contains views for analytics dashboards,
reporting, metrics, and data visualization.
"""

from django.contrib.auth.mixins import PermissionRequiredMixin
from django.core.exceptions import PermissionDenied
from django.views.generic import TemplateView

from employees.organisation_models import Employee
from employees.work_models import WorkItem

from .services import discover_patterns


class AnalyticsOverview(PermissionRequiredMixin, TemplateView):
    """Display departmental pattern discoveries to authorized managers."""

    permission_required = "employees.add_workassignment"
    template_name = "analytics/overview.html"

    def get_context_data(self, **kwargs: object) -> dict[str, object]:
        """Scope every analytical result to the signed-in employee department."""
        context = super().get_context_data(**kwargs)
        user = self.request.user
        employee = (
            Employee.objects.select_related("department").filter(user=user).first()
            if user.is_authenticated
            else None
        )
        if employee is None:
            raise PermissionDenied("Only employees can access analytics.")

        work_items = WorkItem.objects.filter(issue_type__department=employee.department)
        analysis = discover_patterns(work_items)
        context["department_name"] = employee.department.name
        context["record_count"] = analysis["record_count"]
        context["findings"] = analysis["findings"]
        context["limitations"] = analysis["limitations"]
        context["generated_at"] = analysis["generated_at"]
        return context
