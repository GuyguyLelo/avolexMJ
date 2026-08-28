"""URLs dossiers."""

from __future__ import annotations

from django.urls import path

from apps.matters import views

app_name = "matters"

urlpatterns = [
    path("", views.MatterListView.as_view(), name="list"),
    path("nouveau/", views.MatterCreateView.as_view(), name="create"),
    path(
        "api/contexte-dossier/",
        views.MatterCreateContextView.as_view(),
        name="create_context",
    ),
    path("<uuid:pk>/", views.MatterDetailView.as_view(), name="detail"),
    path("<uuid:pk>/modifier/", views.MatterUpdateView.as_view(), name="update"),
    path("<uuid:pk>/archiver/", views.MatterArchiveView.as_view(), name="archive"),
    path("<uuid:pk>/supprimer/", views.MatterDeleteView.as_view(), name="delete"),
]
