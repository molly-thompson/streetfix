"""URL configuration for the intake application.

This module defines URL patterns for the intake app,
with the public report chat as the home page and its JSON API.
"""

from django.urls import path

from .views import (
    CreateReportView,
    NearbyReportView,
    OldReportLinkView,
    ReportChatView,
    ReportStatusView,
)

app_name = "intake"

urlpatterns = [
    # The report chat is the public home page; "form_intake" is the name the
    # rest of the site uses for "home" (logo, sign-out, error pages).
    path("", ReportChatView.as_view(), name="form_intake"),
    # Older links to /report/ still reach the chat.
    path("report/", OldReportLinkView.as_view()),
    path("api/cases/", CreateReportView.as_view(), name="create_report"),
    path("api/cases/nearby/", NearbyReportView.as_view(), name="nearby_report"),
    path(
        "api/cases/<str:reference>/",
        ReportStatusView.as_view(),
        name="report_status",
    ),
]
