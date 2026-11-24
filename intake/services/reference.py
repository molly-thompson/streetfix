"""Public report references and the status a reporter may see for them."""

from django.conf import settings

from employees.work_models import WorkItem
from intake.models import ReportSubmission

CODE_LENGTH = 8
REVIEW_STATUS: dict[str, str] = {
    ReportSubmission.TriageState.RECEIVED: "Received",
    ReportSubmission.TriageState.NEEDS_REVIEW: "Under review",
    ReportSubmission.TriageState.OUT_OF_SCOPE: "Reviewed",
}


def display_reference(submission: ReportSubmission) -> str:
    """Return the reference to show a reporter: the deployment prefix, then the code."""
    code = submission.public_reference
    return f"{settings.INTAKE_REFERENCE_PREFIX}{code[:4]}-{code[4:]}"


def submission_for_reference(reference: str) -> ReportSubmission | None:
    """Find the submission a reporter's reference points to, if any."""
    text = reference.strip().upper()
    prefix = settings.INTAKE_REFERENCE_PREFIX.upper()
    code = text.removeprefix(prefix).replace("-", "").replace(" ", "")
    if len(code) != CODE_LENGTH:
        return None
    return (
        ReportSubmission.objects.select_related(
            "work_item__status", "reported_issue_type"
        )
        .filter(public_reference=code)
        .first()
    )


def public_status(submission: ReportSubmission) -> str:
    """Describe progress without revealing review decisions or personal details."""
    if submission.work_item is not None:
        return str(submission.work_item.status.label)
    return REVIEW_STATUS.get(str(submission.triage_state), "Received")


def reference_for_work_item(work_item: WorkItem) -> str | None:
    """Return the reference of the earliest report behind a work item, if any."""
    submission = work_item.submissions.order_by("pk").first()
    return display_reference(submission) if submission is not None else None
