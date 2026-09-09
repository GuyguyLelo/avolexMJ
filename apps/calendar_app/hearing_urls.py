"""URLs module Audiences."""

from __future__ import annotations

from django.urls import path

from apps.calendar_app import views

app_name = "hearings"

urlpatterns = [
    path("", views.HearingListView.as_view(), name="list"),
    path("nouvelle/", views.HearingCreateView.as_view(), name="create"),
    path("<uuid:pk>/modifier/", views.HearingUpdateView.as_view(), name="update"),
    path("<uuid:pk>/rapport/", views.HearingReportView.as_view(), name="report"),
    path(
        "<uuid:pk>/rapport/telecharger/",
        views.HearingReportDownloadView.as_view(),
        name="report_download",
    ),
    path(
        "<uuid:pk>/rapport/apercu/",
        views.HearingReportPreviewView.as_view(),
        name="report_preview",
    ),
    path(
        "<uuid:pk>/pieces/<uuid:attachment_id>/telecharger/",
        views.HearingAttachmentDownloadView.as_view(),
        name="attachment_download",
    ),
    path(
        "<uuid:pk>/pieces/<uuid:attachment_id>/apercu/",
        views.HearingAttachmentPreviewView.as_view(),
        name="attachment_preview",
    ),
    path(
        "<uuid:pk>/pieces/<uuid:attachment_id>/supprimer/",
        views.HearingAttachmentDeleteView.as_view(),
        name="attachment_delete",
    ),
    path("<uuid:pk>/statut/", views.HearingStatusView.as_view(), name="status"),
]
