"""URLs de l'app core."""

from __future__ import annotations

from django.urls import path

from .views import HealthCheckView, HomeView, LandingView, SupervisionView

app_name = "core"

urlpatterns = [
    path("", LandingView.as_view(), name="landing"),
    path("app/", HomeView.as_view(), name="home"),
    path("app/supervision/", SupervisionView.as_view(), name="supervision"),
    path("health/", HealthCheckView.as_view(), name="health"),
]
