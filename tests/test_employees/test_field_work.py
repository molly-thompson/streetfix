"""Tests for the officer's on-site flow and phone screens."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

import cloudinary.exceptions
import cloudinary.uploader
import pytest
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse

from employees import field_work
from employees.dispatch import assign_work
from employees.organisation_models import Employee
from employees.visit_report import VisitReportForm
from employees.work_models import (
    WorkItem,
    WorkItemComment,
    WorkItemPhoto,
    WorkItemReport,
    WorkItemStatus,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def media_root(settings: Any, tmp_path: Path) -> None:
    """Keep uploaded test photos out of the project folder."""
    settings.MEDIA_ROOT = tmp_path


def photo(name: str = "site.jpg") -> SimpleUploadedFile:
    """Return a small uploaded image."""
    return SimpleUploadedFile(name, b"fake-jpeg-bytes", content_type="image/jpeg")


def started(job: WorkItem, officer: Employee) -> WorkItemReport:
    """Arrive, add a before photo and start work."""
    report = field_work.arrive(job, officer)
    field_work.add_photo(
        report, photo(), tag=WorkItemPhoto.Tag.BEFORE, employee=officer
    )
    field_work.start_work(report, officer)
    job.refresh_from_db()
    return report


def test_my_work_lists_active_jobs_only(
    job: WorkItem,
    officer: Employee,
    make_work_item: Callable[..., WorkItem],
) -> None:
    """Officers see the work they are on, not other people's."""
    make_work_item()

    assert list(field_work.my_work(officer)) == [job]


def test_arriving_records_the_time_once(job: WorkItem, officer: Employee) -> None:
    """Arriving twice keeps the first arrival time and one draft."""
    first = field_work.arrive(job, officer)
    again = field_work.arrive(job, officer)

    assert first.pk == again.pk
    assert again.arrived_at == first.arrived_at


def test_only_the_case_officer_can_arrive(
    job: WorkItem, make_employee: Callable[..., Employee], manager: Employee
) -> None:
    """Support staff cannot run the job."""
    helper = make_employee("dan")
    assign_work(job, helper, case_officer=False, dispatcher=manager)

    with pytest.raises(ValidationError):
        field_work.arrive(job, helper)


def test_work_cannot_start_without_a_before_photo(
    job: WorkItem, officer: Employee
) -> None:
    """A before photo, or a proper reason, is needed to start."""
    report = field_work.arrive(job, officer)

    with pytest.raises(ValidationError):
        field_work.start_work(report, officer, no_photo_reason="no")


def test_a_reason_lets_work_start_without_a_photo(
    job: WorkItem, officer: Employee
) -> None:
    """The reason is kept on the report for the manager."""
    report = field_work.arrive(job, officer)

    field_work.start_work(
        report, officer, no_photo_reason="Live gas leak, made safe first"
    )

    job.refresh_from_db()
    report.refresh_from_db()
    assert job.status.code == "IN_PROGRESS"
    assert report.no_before_photo_reason == "Live gas leak, made safe first"


def test_starting_work_is_recorded_in_history(job: WorkItem, officer: Employee) -> None:
    """Starting work moves the job to In progress, by the officer."""
    started(job, officer)

    change = job.status_history.last()
    assert change is not None
    assert change.new_status.code == "IN_PROGRESS"
    assert change.changed_by == officer


@pytest.mark.parametrize(
    ("outcome", "status"),
    [
        (WorkItemReport.Outcome.FIXED, "RESOLVED"),
        (WorkItemReport.Outcome.NO_FAULT_FOUND, "RESOLVED"),
        (WorkItemReport.Outcome.NO_ACCESS, "ON_HOLD"),
    ],
)
def test_submitting_moves_the_job_on(
    job: WorkItem, officer: Employee, outcome: str, status: str
) -> None:
    """The outcome decides where the job goes next."""
    report = started(job, officer)
    report.outcome = outcome
    report.work_done = "Cut out and filled the pothole with hot asphalt"
    report.save()

    field_work.submit_report(report, officer)

    job.refresh_from_db()
    assert report.is_submitted
    assert job.status.code == status


def test_reported_jobs_leave_the_list(job: WorkItem, officer: Employee) -> None:
    """Once reported, the job shows under reported today instead."""
    report = started(job, officer)
    report.outcome = WorkItemReport.Outcome.NO_ACCESS
    report.save()
    field_work.submit_report(report, officer)

    assert list(field_work.my_work(officer)) == []
    assert list(field_work.reported_today(officer)) == [report]


def test_my_jobs_page_shows_next_job(officer_client: Client, job: WorkItem) -> None:
    """The officer's home page leads with their next job."""
    response = officer_client.get(reverse("employees:my_jobs"))

    assert response.status_code == 200
    assert response.context["hero"] == job
    assert b"I have arrived on site" in response.content


def test_officer_pages_need_an_employee(
    client: Client, django_user_model: type[User]
) -> None:
    """Accounts without an employee profile are refused."""
    client.force_login(django_user_model.objects.create_user(username="public"))

    assert client.get(reverse("employees:my_jobs")).status_code == 403


def test_other_peoples_jobs_are_not_found(
    officer_client: Client, make_work_item: Callable[..., WorkItem]
) -> None:
    """Officers can only open work they are on."""
    other = make_work_item()

    response = officer_client.get(reverse("employees:my_job", args=[other.pk]))

    assert response.status_code == 404


def test_arrive_button_leads_to_before_photo(
    officer_client: Client, job: WorkItem
) -> None:
    """Arriving takes the officer straight to the before photo."""
    response = officer_client.post(
        reverse("employees:my_job", args=[job.pk]), {"arrive": ""}
    )

    assert response.headers["Location"] == reverse(
        "employees:before_photo", args=[job.pk]
    )


def test_before_photo_upload_and_start(
    officer_client: Client, job: WorkItem, officer: Employee
) -> None:
    """Uploading a before photo then starting puts the job in progress."""
    url = reverse("employees:before_photo", args=[job.pk])
    officer_client.post(url, {"photo": photo()})

    response = officer_client.post(url, {"start": ""})

    job.refresh_from_db()
    assert response.status_code == 302
    assert job.status.code == "IN_PROGRESS"
    assert WorkItemPhoto.objects.filter(
        tag=WorkItemPhoto.Tag.BEFORE, uploaded_by=officer
    ).exists()


def test_non_images_are_refused(officer_client: Client, job: WorkItem) -> None:
    """Only image files are accepted as photos."""
    bad = SimpleUploadedFile("notes.txt", b"hello", content_type="text/plain")

    response = officer_client.post(
        reverse("employees:before_photo", args=[job.pk]), {"photo": bad}
    )

    assert response.status_code == 200
    assert not WorkItemPhoto.objects.exists()


COMPLETE_ANSWERS = {
    "outcome": "FIXED",
    "findings": "Pothole 400mm wide, 80mm deep",
    "work_done": "Cut out the edges and filled with hot asphalt",
    "materials": "6 bags asphalt",
    "resolved": "yes",
    "additional_found": "0",
    "outstanding": "0",
    "confirm_accurate": "on",
    "confirm_recorded": "on",
    "confirm_outstanding": "on",
    "confirm_photos": "on",
    "confirm_safety": "on",
}


def test_report_saves_draft_then_submits(
    officer_client: Client, job: WorkItem, officer: Employee
) -> None:
    """Adding a photo keeps what was typed; submitting resolves the job."""
    started(job, officer)
    url = reverse("employees:visit_report", args=[job.pk])
    officer_client.post(url, {**COMPLETE_ANSWERS, "photo": photo("after.jpg")})

    draft = field_work.draft_report(job, officer)
    assert draft is not None
    assert draft.materials == "6 bags asphalt"
    assert draft.extra_answers["resolved"] == "yes"
    assert draft.extra_answers["outstanding"] is False
    assert draft.photos.filter(tag=WorkItemPhoto.Tag.AFTER).exists()

    response = officer_client.post(url, {**COMPLETE_ANSWERS, "finish": ""})

    summary_url = reverse("employees:visit_summary", args=[job.pk])
    assert response.headers["Location"] == summary_url
    job.refresh_from_db()
    assert job.status.code == "IN_PROGRESS"

    response = officer_client.post(summary_url, {"summary": "Pothole filled."})

    job.refresh_from_db()
    assert response.headers["Location"] == reverse("employees:my_jobs")
    assert job.status.code == "RESOLVED"


def test_report_shows_what_is_missing(
    officer_client: Client, job: WorkItem, officer: Employee
) -> None:
    """Submitting without an outcome lists the problem."""
    started(job, officer)

    response = officer_client.post(
        reverse("employees:visit_report", args=[job.pk]), {"finish": ""}
    )

    assert response.status_code == 200
    assert b"Select a job outcome." in response.content


def report_problems(job: WorkItem, officer: Employee, **answers: str) -> list[str]:
    """Return what the report form says is missing for these answers."""
    report = started(job, officer)
    form = VisitReportForm({**COMPLETE_ANSWERS, **answers}, instance=report)
    assert form.is_valid(), form.errors
    return form.problems(report)


def test_complete_report_has_no_problems(job: WorkItem, officer: Employee) -> None:
    """A fully answered report with an after photo can be sent."""
    report = started(job, officer)
    field_work.add_photo(report, photo(), tag=WorkItemPhoto.Tag.AFTER, employee=officer)
    form = VisitReportForm(COMPLETE_ANSWERS, instance=report)

    assert form.is_valid()
    assert form.problems(report) == []


def test_vague_work_description_is_refused(job: WorkItem, officer: Employee) -> None:
    """Saying the job is completed does not describe the work."""
    problems = report_problems(job, officer, work_done="Job completed")

    assert any("be specific" in problem for problem in problems)


def test_fixed_jobs_need_an_after_photo(job: WorkItem, officer: Employee) -> None:
    """Fixed work needs an after photo, or a reason there isn't one."""
    assert "Add an AFTER photo" in report_problems(job, officer)[0]


def test_photo_exception_excuses_missing_photo(
    job: WorkItem, officer: Employee
) -> None:
    """A proper reason stands in for the missing photo."""
    problems = report_problems(
        job, officer, photo_exception="Police cordon stopped access"
    )

    assert problems == []


def test_further_work_outcome_needs_the_further_work_section(
    job: WorkItem, officer: Employee
) -> None:
    """Choosing further work asks for the re-triage details."""
    problems = report_problems(
        job,
        officer,
        outcome="FURTHER_WORK",
        photo_exception="Police cordon stopped access",
    )

    assert "Further work: choose a reason." in problems
    assert "Further work: was the site left safe?" in problems


def test_unsafe_site_needs_a_safety_report(job: WorkItem, officer: Employee) -> None:
    """Leaving a site unsafe must be reported under health and safety."""
    problems = report_problems(
        job,
        officer,
        outcome="FURTHER_WORK",
        further_site_safe="no",
        photo_exception="Police cordon stopped access",
    )

    assert "Site not left safe — complete the Health & Safety section." in problems


def test_missing_confirmations_are_flagged(job: WorkItem, officer: Employee) -> None:
    """All five confirmations must be ticked."""
    problems = report_problems(
        job,
        officer,
        confirm_safety="",
        photo_exception="Police cordon stopped access",
    )

    assert problems == ["Tick all five confirmations."]


def test_further_work_answers_mark_further_work_needed(
    officer_client: Client, job: WorkItem, officer: Employee
) -> None:
    """Outstanding work flags the report as needing further work."""
    started(job, officer)
    officer_client.post(
        reverse("employees:visit_report", args=[job.pk]),
        {
            **COMPLETE_ANSWERS,
            "outstanding": "1",
            "outstanding_text": "Kerb needs relaying",
        },
    )

    draft = field_work.draft_report(job, officer)
    assert draft is not None
    assert draft.further_work_needed
    assert draft.extra_answers["outstanding_text"] == "Kerb needs relaying"


def test_comment_reaches_the_job(
    officer_client: Client, job: WorkItem, officer: Employee
) -> None:
    """Comments from the job page are saved for the manager."""
    officer_client.post(
        reverse("employees:my_job", args=[job.pk]), {"content": "Need a breaker"}
    )

    comment = WorkItemComment.objects.get()
    assert comment.author == officer
    assert comment.content == "Need a breaker"


def test_map_and_alerts_pages(
    officer_client: Client, job: WorkItem, manager: Employee
) -> None:
    """The map lists the officer's stops and alerts show manager comments."""
    field_work.add_comment(job, manager, "Bring cones, busy junction")

    map_page = officer_client.get(reverse("employees:my_map"))
    alerts = officer_client.get(reverse("employees:my_alerts"))

    assert map_page.context["map_points"]["stops"][0]["url"] == reverse(
        "employees:my_job", args=[job.pk]
    )
    assert b"Bring cones, busy junction" in alerts.content


def test_my_jobs_can_show_a_map(officer_client: Client, job: WorkItem) -> None:
    """The list/map switch adds the route map."""
    response = officer_client.get(reverse("employees:my_jobs") + "?show=map")

    assert response.context["map_points"] is not None


def test_photos_go_to_cloudinary_when_configured(
    job: WorkItem,
    officer: Employee,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With Cloudinary set up, the photo's Cloudinary address is saved."""
    settings.OFFICER_PHOTOS_ON_CLOUDINARY = True
    uploads: list[dict[str, Any]] = []

    def fake_upload(file: Any, **options: Any) -> dict[str, str]:
        uploads.append(options)
        return {"secure_url": "https://res.cloudinary.com/demo/image/upload/a.jpg"}

    monkeypatch.setattr(cloudinary.uploader, "upload", fake_upload)
    report = field_work.arrive(job, officer)

    saved = field_work.add_photo(
        report, photo(), tag=WorkItemPhoto.Tag.BEFORE, employee=officer
    )

    assert saved.image_url == "https://res.cloudinary.com/demo/image/upload/a.jpg"
    assert uploads[0]["folder"] == f"streetfix/work-photos/{job.pk}"


def test_failed_cloudinary_upload_is_shown_to_the_officer(
    officer_client: Client,
    job: WorkItem,
    settings: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If the upload fails, the officer is told and nothing is saved."""
    settings.OFFICER_PHOTOS_ON_CLOUDINARY = True

    def broken_upload(file: Any, **options: Any) -> dict[str, str]:
        raise cloudinary.exceptions.Error("service unavailable")

    monkeypatch.setattr(cloudinary.uploader, "upload", broken_upload)

    response = officer_client.post(
        reverse("employees:before_photo", args=[job.pk]), {"photo": photo()}
    )

    assert response.status_code == 200
    assert b"The photo could not be uploaded. Try again." in response.content
    assert not WorkItemPhoto.objects.exists()


def test_officer_status_uses_status_labels_from_the_admin(
    officer_client: Client, job: WorkItem
) -> None:
    """Renaming a status in the admin renames the officer's job chip."""
    WorkItemStatus.objects.filter(code="ASSIGNED").update(label="Allocated")

    response = officer_client.get(reverse("employees:my_jobs"))

    assert b">Allocated</span>" in response.content


def test_comment_box_is_a_textarea(officer_client: Client, job: WorkItem) -> None:
    """The job page's comment box keeps dictation and its placeholder."""
    response = officer_client.get(reverse("employees:my_job", args=[job.pk]))
    content = response.content.decode()

    assert '<textarea name="content"' in content
    assert "data-dictate" in content
    assert 'placeholder="Write a comment…"' in content
