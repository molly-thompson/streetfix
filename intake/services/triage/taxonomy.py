"""Capture the issue taxonomy and routing referenced by a policy version."""

from typing import Any

from employees.organisation_models import Department, IssueType


def snapshot_taxonomy(*, lock: bool = False) -> dict[str, Any]:
    """Capture stable issue and department fields in deterministic order."""
    issues = IssueType.objects.order_by("pk")
    if lock:
        issues = issues.select_for_update()
    issue_data = list(
        issues.values(
            "id",
            "name",
            "code",
            "kind",
            "parent_id",
            "department_id",
            "sensitive_content_enabled",
        )
    )
    department_ids = {
        issue["department_id"]
        for issue in issue_data
        if issue["department_id"] is not None
    }
    departments = Department.objects.filter(pk__in=department_ids).order_by("pk")
    if lock:
        departments = departments.select_for_update()
    return {
        "issues": issue_data,
        "departments": list(departments.values("id", "name")),
    }
