"""URLs de l'app core."""

from __future__ import annotations

from django.urls import path

from apps.accounts.views import AvoLexLoginView

from .views import HealthCheckView, HomeView, LandingView, SettingsHubView, SupervisionView

app_name = "core"

urlpatterns = [
    path("", AvoLexLoginView.as_view(), name="root"),
    path("accueil/", LandingView.as_view(), name="landing"),
    path("app/", HomeView.as_view(), name="home"),
    path("app/supervision/", SupervisionView.as_view(), name="supervision"),
    path("app/parametres/", SettingsHubView.as_view(), name="settings"),
    path("health/", HealthCheckView.as_view(), name="health"),
]
