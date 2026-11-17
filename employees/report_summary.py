"""The case note written from an officer's visit report.

The answers are turned into a plain written summary. The officer reads,
edits and approves it before it is saved as a comment on the job.
"""

from .work_models import Priority, WorkItemReport

Outcome = WorkItemReport.Outcome


def _yes_no(value: object) -> str | None:
    if value is True:
        return "yes"
    if value is False:
        return "no"
    return None


def plain_summary(report: WorkItemReport) -> str:
    """Write the report's answers out as a plain case note."""
    answers = report.extra_answers or {}
    lines: list[str] = []

    if report.outcome:
        lines.append(f"Outcome: {Outcome(report.outcome).label}.")
    resolved = answers.get("resolved")
    if resolved:
        lines.append(f"Issue resolved: {resolved}.")
    for label, value in (
        ("Found on site", report.findings),
        ("Actions taken", answers.get("actions")),
        ("Work done", report.work_done),
        ("Materials used", report.materials),
    ):
        if value and str(value).strip():
            lines.append(f"{label}: {str(value).strip()}")

    if answers.get("additional_found"):
        lines.append(
            "Additional problems found: "
            + (answers.get("additional_text") or "yes").strip()
        )
    if answers.get("outstanding"):
        lines.append(
            "Outstanding issues: " + (answers.get("outstanding_text") or "yes").strip()
        )

    if report.further_work_needed:
        further: list[str] = []
        reasons = answers.get("further_reasons") or []
        if reasons:
            further.append("Reasons: " + "; ".join(reasons) + ".")
        for label, key in (
            ("Explanation", "further_explanation"),
            ("Why it could not be finished", "further_why_not"),
            ("Next steps", "further_next_steps"),
            ("Equipment needed", "further_equipment"),
        ):
            value = answers.get(key)
            if value and str(value).strip():
                further.append(f"{label}: {str(value).strip()}")
        if answers.get("further_specialist"):
            further.append(
                "Specialist needed: "
                + (answers.get("further_specialist_text") or "yes").strip()
            )
        if answers.get("further_urgent"):
            further.append("Marked as urgent.")
        code = answers.get("further_suggested_priority")
        if code:
            priority = Priority.objects.filter(code=code).first()
            further.append(
                f"Suggested priority: {priority.label if priority else code}."
            )
        site_safe = answers.get("further_site_safe")
        if site_safe:
            further.append(f"Site left safe: {site_safe}.")
        lines.append("Further work needed. " + " ".join(further))

    if answers.get("safety_report"):
        safety: list[str] = []
        hazards = answers.get("safety_hazards") or []
        if hazards:
            safety.append("Hazards: " + "; ".join(hazards) + ".")
        description = answers.get("safety_description")
        if description and str(description).strip():
            safety.append(str(description).strip())
        immediate = _yes_no(answers.get("safety_immediate"))
        if immediate:
            safety.append(f"Needs immediate action: {immediate}.")
        lines.append("Health and safety concern reported. " + " ".join(safety))

    if report.no_before_photo_reason.strip():
        lines.append(f"No before photo: {report.no_before_photo_reason.strip()}")
    elif answers.get("photo_exception"):
        lines.append(f"Photo note: {str(answers['photo_exception']).strip()}")

    if report.additional_notes.strip():
        lines.append(f"Notes: {report.additional_notes.strip()}")

    return "\n".join(lines) or "Visit report submitted."
