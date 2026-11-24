"""URL configuration for the employees application.

This module defines URL patterns for the employees app: the manager
pages, and the phone screens officers use on site.
"""

from django.urls import path

from .officer_views import (
    AlertsView,
    BeforePhotoView,
    JobView,
    MapView,
    MyJobsView,
    VisitReportView,
    VisitSummaryView,
)
from .views import DispatchDetailView, DispatchListView, EmployeeDashboardView

app_name = "employees"

urlpatterns = [
    path("", EmployeeDashboardView.as_view(), name="dashboard"),
    path("dispatch/", DispatchListView.as_view(), name="dispatch"),
    path(
        "dispatch/<int:pk>/",
        DispatchDetailView.as_view(),
        name="dispatch_detail",
    ),
    path("my-jobs/", MyJobsView.as_view(), name="my_jobs"),
    path("my-jobs/map/", MapView.as_view(), name="my_map"),
    path("my-jobs/alerts/", AlertsView.as_view(), name="my_alerts"),
    path("my-jobs/<int:pk>/", JobView.as_view(), name="my_job"),
    path(
        "my-jobs/<int:pk>/before-photo/",
        BeforePhotoView.as_view(),
        name="before_photo",
    ),
    path("my-jobs/<int:pk>/report/", VisitReportView.as_view(), name="visit_report"),
    path(
        "my-jobs/<int:pk>/report/summary/",
        VisitSummaryView.as_view(),
        name="visit_summary",
    ),
]
