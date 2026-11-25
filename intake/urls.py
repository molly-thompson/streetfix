"""URL configuration for the intake application.

This module defines URL patterns for the intake app,
with the public report chat as the home page and its JSON API.
"""

from django.urls import path

from .public_views import IssueSearchApiView, IssueSearchView, TrackReportsView
from .report_views import (
    PhotoAuthorizeView,
    PhotoVerifyView,
    ReportReceivedView,
    SubmitReportView,
)
from .views import (
    AcceptReportView,
    AssessDuplicatesView,
    CorrectLocationView,
    CreateReportView,
    DuplicateReviewView,
    FinalizedReportListView,
    NearbyReportView,
    OldReportLinkView,
    OutOfScopeView,
    RecoverReportView,
    ReopenReportView,
    ReportChatView,
    ReportPhotoView,
    ReportStatusView,
    RequestEngineAssessmentView,
    ReviewDetailView,
    ReviewQueueView,
)

app_name = "intake"

urlpatterns = [
    # The report chat is the public home page; "form_intake" is the name the
    # rest of the site uses for "home" (logo, sign-out, error pages).
    path("", ReportChatView.as_view(), name="form_intake"),
    # Older links to /report/ still reach the chat.
    path("report/", OldReportLinkView.as_view()),
    path("report/form/", SubmitReportView.as_view(), name="submit_report"),
    path("report/form/received/", ReportReceivedView.as_view(), name="report_received"),
    path("report/photos/", PhotoAuthorizeView.as_view(), name="photo_authorize"),
    path("track/", TrackReportsView.as_view(), name="track_reports"),
    path("issues/", IssueSearchView.as_view(), name="search_issues"),
    path("api/issues/", IssueSearchApiView.as_view(), name="search_issues_api"),
    path(
        "report/photos/<uuid:draft_id>/<uuid:slot_id>/verify/",
        PhotoVerifyView.as_view(),
        name="photo_verify",
    ),
    path("review/", ReviewQueueView.as_view(), name="review_queue"),
    path(
        "review/photos/<uuid:slot_id>/", ReportPhotoView.as_view(), name="report_photo"
    ),
    path(
        "review/finalized/", FinalizedReportListView.as_view(), name="finalized_reports"
    ),
    path(
        "review/finalized/<int:pk>/", ReopenReportView.as_view(), name="reopen_report"
    ),
    path("review/<int:pk>/", ReviewDetailView.as_view(), name="review_detail"),
    path(
        "review/<int:pk>/assess-duplicates/",
        AssessDuplicatesView.as_view(),
        name="assess_duplicates",
    ),
    path(
        "review/<int:pk>/assessment/",
        RequestEngineAssessmentView.as_view(),
        name="request_engine_assessment",
    ),
    path(
        "review/<int:pk>/recover/", RecoverReportView.as_view(), name="recover_report"
    ),
    path(
        "review/<int:pk>/location/",
        CorrectLocationView.as_view(),
        name="correct_location",
    ),
    path(
        "review/<int:pk>/out-of-scope/", OutOfScopeView.as_view(), name="out_of_scope"
    ),
    path(
        "review/<int:pk>/duplicate/",
        DuplicateReviewView.as_view(),
        name="duplicate_review",
    ),
    path("review/<int:pk>/accept/", AcceptReportView.as_view(), name="accept_report"),
    path("api/cases/", CreateReportView.as_view(), name="create_report"),
    path("api/cases/nearby/", NearbyReportView.as_view(), name="nearby_report"),
    path(
        "api/cases/<str:reference>/",
        ReportStatusView.as_view(),
        name="report_status",
    ),
]
