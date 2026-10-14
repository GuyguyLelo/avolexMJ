"""URLs procurations."""

from __future__ import annotations

from django.urls import path

from apps.procurations import views

app_name = "procurations"

urlpatterns = [
    path("", views.ProcurationListView.as_view(), name="list"),
    path("nouveau/", views.ProcurationCreateView.as_view(), name="create"),
    path("<uuid:pk>/", views.ProcurationDetailView.as_view(), name="detail"),
    path("<uuid:pk>/modifier/", views.ProcurationUpdateView.as_view(), name="update"),
    path("<uuid:pk>/transmettre/", views.ProcurationSubmitView.as_view(), name="submit"),
    path(
        "<uuid:pk>/valider-conseiller/",
        views.ProcurationApproveConseillerView.as_view(),
        name="approve_conseiller",
    ),
    path("<uuid:pk>/accorder/", views.ProcurationGrantView.as_view(), name="grant"),
    path("<uuid:pk>/refuser/", views.ProcurationRefuseView.as_view(), name="refuse"),
    path("<uuid:pk>/revoquer/", views.ProcurationRevokeView.as_view(), name="revoke"),
    path("<uuid:pk>/generer/", views.ProcurationGenerateView.as_view(), name="generate"),
    path("<uuid:pk>/editeur/", views.ProcurationEditorView.as_view(), name="editor"),
    path("<uuid:pk>/supprimer/", views.ProcurationDeleteView.as_view(), name="delete"),
    path("<uuid:pk>/acte/", views.ProcurationDownloadView.as_view(), name="download"),
    path("<uuid:pk>/acte/apercu/", views.ProcurationPreviewView.as_view(), name="preview"),
    path("<uuid:pk>/acte/pdf/", views.ProcurationPdfDownloadView.as_view(), name="pdf"),
    path("<uuid:pk>/acte/word/", views.ProcurationWordView.as_view(), name="word"),
]
